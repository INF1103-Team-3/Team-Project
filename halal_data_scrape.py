#!/usr/bin/env python3
"""
Scrape HalalFreak profile pages for full details + coordinates.

Three-phase design for speed and completeness:
  Phase 1   — fetch all profile pages in parallel (fast, no geocoding).
  Phase 2   — geocode *unique* postal codes in parallel (deduped).
  Repair    — address-based fallback for any record still missing coords.

Postal codes are geocoded via OneMap. Because many restaurants share a
postal code (same mall/building), deduping usually cuts OneMap calls by
several times versus geocoding per-restaurant.

Output: data/HalalFreak_certified.json

Resumable: re-run after Ctrl+C and it picks up where it left off.
"""

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup

INPUT = Path("data/HalalFreak_restaurants.json")
OUTPUT = Path("data/HalalFreak_certified.json")
PROGRESS = Path("data/HalalFreak_certified.progress.json")
GEOCODE_CACHE = Path("data/onemap_postal_cache.json")

HEADERS = {"User-Agent": "HalalNav/1.0 (personal project; contact@example.com)"}

# Phase 1 (profile fetch) tuning — these are just requests to halalfreak.
FETCH_WORKERS = 16
FETCH_SAVE_EVERY = 30

# Phase 2 (OneMap) tuning — semaphore caps concurrent OneMap calls.
ONEMAP_WORKERS = 8
ONEMAP_CONCURRENCY = 8
ONEMAP_SAVE_EVERY = 25

# Repair pass — one worker, low concurrency, cheap.
REPAIR_WORKERS = 6
REPAIR_SAVE_EVERY = 25

TIMEOUT = 15
CERT_FALLBACK_RE = re.compile(r"\b(E[A-Z]{2,}\d{6,})\b")
POSTAL_RE = re.compile(r"(\d{6})")

# Street suffixes we trust to mark the end of the street name.
_STREET_SUFFIX_RE = re.compile(
    r"\b(Road|Street|Avenue|Drive|Lane|Crescent|Walk|Place|Close|"
    r"Terrace|Way|Link|Rise|Circle|Central|Boulevard|Highway|Hill|"
    r"Park|Grove|View|Square|Quay|Gardens?|Parkway|Jalan|Lorong)\b",
    re.IGNORECASE,
)

_thread_local = threading.local()
_lock = threading.Lock()
_geocode_lock = threading.Lock()
_postal_cache = {}

# Cap concurrent OneMap calls to avoid 429 throttling.
_ONEMAP_SEM = threading.Semaphore(ONEMAP_CONCURRENCY)

# Prefix used for address keys in the same cache dict.
ADDR_PREFIX = "addr:"


# ---------- postal-code normalization ----------

def normalize_postal(value):
    """Canonicalize a postal code to a 6-digit string, or "".

    Handles formats like:
      "123456"           -> "123456"
      "Singapore 123456" -> "123456"
      "S(123456)"        -> "123456"
      "  123456  "       -> "123456"
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    m = POSTAL_RE.search(s)
    if m:
        return m.group(1)
    return s  # non-standard; return as-is so we don't silently lose data


def pick_postal(entry, parsed):
    """Pick the postal code for a record, using the SAME precedence as
    collect_unique_postals. Returns the normalized key."""
    raw = (entry.get("postal_code")
           or parsed.get("postal_code_from_page")
           or "")
    return normalize_postal(raw)


def pick_address(entry, parsed):
    """Pick the best address for a record (page first, then index)."""
    raw = (parsed.get("address")
           or entry.get("address")
           or "")
    return str(raw).strip()


# ---------- address candidate generation ----------

def _address_candidates(addr):
    """Yield progressively simpler variants of an address.

    OneMap's elastic search can't parse unit numbers ("#01-24") or mall
    names appended to the street. We try the full string first, then
    strip back to just "<block> <street name>".
    """
    seen = set()

    def _clean(a):
        a = re.sub(r"\s+", " ", a).strip(" ,")
        return a

    def _emit(a):
        a = _clean(a)
        if a and a.lower() not in seen:
            seen.add(a.lower())
            return a
        return None

    # 1. Original, untouched.
    c = _emit(addr)
    if c:
        yield c

    # 2. Everything before the first '#' (drops unit + mall).
    no_unit = re.sub(r"\s*#.*$", "", addr)
    c = _emit(no_unit)
    if c:
        yield c

    # 3. Up to and including the first street suffix.
    base = no_unit or addr
    m = _STREET_SUFFIX_RE.search(base)
    if m:
        up_to = base[:m.end()]
        c = _emit(up_to)
        if c:
            yield c

    # 4. Just the street name onwards (drop block number).
    if m:
        rest = base[m.start():]
        c = _emit(rest)
        if c:
            yield c


# ---------- HTTP session ----------

def get_session():
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update(HEADERS)
        _thread_local.session = s
    return _thread_local.session


# ---------- OneMap geocoding ----------

def load_postal_cache():
    """Load cache, dropping poisoned nulls so they get retried."""
    global _postal_cache
    if GEOCODE_CACHE.exists():
        try:
            raw = json.loads(GEOCODE_CACHE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        _postal_cache = {
            k: v for k, v in raw.items()
            if isinstance(v, dict) and v.get("lat") is not None
        }
        dropped = len(raw) - len(_postal_cache)
        if dropped:
            print(f"  Dropped {dropped} cached nulls (will retry them).",
                  flush=True)
    else:
        _postal_cache = {}
    return _postal_cache


def save_postal_cache():
    GEOCODE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    GEOCODE_CACHE.write_text(
        json.dumps(_postal_cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _onemap_search(search_val):
    """One OneMap elastic/search call. Returns parsed dict or None on
    transient failure."""
    for attempt in range(3):
        with _ONEMAP_SEM:
            try:
                resp = requests.get(
                    "https://www.onemap.gov.sg/api/common/elastic/search",
                    params={
                        "searchVal": search_val,
                        "returnGeom": "Y",
                        "getAddrDetails": "Y",
                        "pageNum": 1,
                    },
                    timeout=10,
                )
                if resp.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError):
                time.sleep(0.5 * (attempt + 1))
                continue
    return None


def _extract_latlng(data):
    """Pull (lat, lng) out of an OneMap response, or (None, None)."""
    if not data or data.get("found", 0) <= 0:
        return None, None
    r0 = data["results"][0]
    try:
        return float(r0["LATITUDE"]), float(r0["LONGITUDE"])
    except (KeyError, ValueError, TypeError):
        return None, None


def geocode_postal(postal_code):
    """OneMap postal lookup → (lat, lng) or (None, None). Cached.

    Only caches a *definitive* answer (match, or clean "no results").
    Transient failures are NOT cached, so a later run will retry.
    """
    if not postal_code:
        return None, None

    key = normalize_postal(postal_code)
    if not key:
        return None, None

    with _geocode_lock:
        if key in _postal_cache:
            entry = _postal_cache[key]
            return entry.get("lat"), entry.get("lng")

    data = _onemap_search(key)
    if data is None:
        return None, None

    lat, lng = _extract_latlng(data)
    with _geocode_lock:
        _postal_cache[key] = {"lat": lat, "lng": lng}
    return lat, lng


def geocode_address(address):
    """OneMap address lookup → (lat, lng) or (None, None). Cached under
    the 'addr:' prefix. Tries progressively simpler variants until one
    yields a match (OneMap chokes on '#01-24' unit numbers and mall
    names appended to the street)."""
    if not address:
        return None, None
    addr = str(address).strip()
    if not addr:
        return None, None

    key = ADDR_PREFIX + addr
    with _geocode_lock:
        if key in _postal_cache:
            entry = _postal_cache[key]
            return entry.get("lat"), entry.get("lng")

    lat, lng = None, None
    got_definitive = False

    for candidate in _address_candidates(addr):
        data = _onemap_search(candidate)
        if data is None:
            # transient — don't trust this as a definitive null
            continue
        got_definitive = True
        lat, lng = _extract_latlng(data)
        if lat is not None:
            break

    if got_definitive:
        with _geocode_lock:
            _postal_cache[key] = {"lat": lat, "lng": lng}
    return lat, lng


# ---------- HTML extraction ----------

def _find_value_after_label(soup, label_text):
    label_lower = label_text.lower()
    for el in soup.find_all(string=True):
        text = el.strip().rstrip(":").lower()
        if text == label_lower:
            parent = el.parent
            if parent.name in ("td", "th"):
                tr = parent.find_parent("tr")
                if tr:
                    cells = tr.find_all(["td", "th"])
                    if len(cells) >= 2:
                        for c in cells:
                            if c is not parent:
                                val = c.get_text(" ", strip=True)
                                if val:
                                    return val
            if parent.name == "dt":
                dd = parent.find_next_sibling("dd")
                if dd:
                    return dd.get_text(" ", strip=True)
            sib = parent.find_next_sibling()
            if sib:
                val = sib.get_text(" ", strip=True)
                if val:
                    return val
    return ""


def extract_profile(html):
    soup = BeautifulSoup(html, "html.parser")
    cert_no = _find_value_after_label(soup, "Certificate no.")
    scheme = _find_value_after_label(soup, "Scheme")
    category = _find_value_after_label(soup, "Category")
    address = _find_value_after_label(soup, "Address")
    postal = _find_value_after_label(soup, "Postal code")
    planning = _find_value_after_label(soup, "Planning area")
    register_date = _find_value_after_label(soup, "In register as of")

    if not cert_no:
        m = CERT_FALLBACK_RE.search(html)
        if m:
            cert_no = m.group(1).upper()

    return {
        "cert_no": cert_no,
        "scheme": scheme,
        "category": category,
        "address": address,
        "postal_code_from_page": postal,
        "planning_area": planning,
        "register_date": register_date,
    }


# ---------- Phase 1: fetch profile pages ----------

def fetch_one(entry):
    """Fetch and parse a single profile page. No geocoding here."""
    url = entry.get("profile_url")
    empty = {
        "cert_no": "", "scheme": "", "category": "", "address": "",
        "postal_code_from_page": "", "planning_area": "", "register_date": "",
    }
    if not url:
        return entry, empty

    session = get_session()
    try:
        resp = session.get(url, timeout=TIMEOUT)
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        parsed = extract_profile(resp.text)
    except (requests.RequestException, ValueError):
        parsed = dict(empty)
    return entry, parsed


def fetch_phase(index, done):
    """Fetch all unfetched profile pages. Updates and returns `done`."""
    remaining = [r for r in index if r.get("profile_url") not in done]
    if not remaining:
        print("Phase 1: nothing to fetch.", flush=True)
        return done

    print(f"Phase 1: fetching {len(remaining)} profile pages "
          f"({FETCH_WORKERS} workers)...", flush=True)

    completed = 0
    t0 = time.time()
    total = len(remaining)

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futures = {pool.submit(fetch_one, e): e for e in remaining}
        try:
            for fut in as_completed(futures):
                try:
                    entry, parsed = fut.result()
                except Exception:
                    entry = futures[fut]
                    parsed = {
                        "cert_no": "", "scheme": "", "category": "",
                        "address": "", "postal_code_from_page": "",
                        "planning_area": "", "register_date": "",
                    }
                done[entry.get("profile_url")] = parsed
                completed += 1

                if completed % FETCH_SAVE_EVERY == 0 or completed == total:
                    save_progress(done)
                    elapsed = time.time() - t0
                    rate = completed / elapsed if elapsed else 0
                    eta = (total - completed) / rate if rate else 0
                    print(f"  [{completed}/{total}]  {rate:.1f}/s  "
                          f"ETA {eta/60:.1f} min", flush=True)
        except KeyboardInterrupt:
            print("\n  Interrupted. Saving progress...", flush=True)
            save_progress(done)
            raise

    save_progress(done)
    return done


# ---------- Phase 2: geocode unique postal codes ----------

def collect_unique_postals(index, done):
    """Return the set of unique normalized postal codes we need coords for."""
    postals = set()
    for entry in index:
        url = entry.get("profile_url")
        parsed = done.get(url, {}) or {}
        pc = pick_postal(entry, parsed)
        if pc:
            postals.add(pc)
    return postals


def geocode_phase(index, done):
    """Geocode every unique postal code. Populates _postal_cache."""
    postals = collect_unique_postals(index, done)

    with _geocode_lock:
        cached = set(_postal_cache.keys())
    todo = sorted(postals - cached)

    print(f"Phase 2: {len(postals)} unique postal codes, "
          f"{len(cached & postals)} already cached, "
          f"{len(todo)} to geocode ({ONEMAP_WORKERS} workers, "
          f"concurrency {ONEMAP_CONCURRENCY})...", flush=True)

    if not todo:
        print("Phase 2: nothing to geocode.", flush=True)
        return

    completed = 0
    t0 = time.time()
    total = len(todo)

    with ThreadPoolExecutor(max_workers=ONEMAP_WORKERS) as pool:
        futures = {pool.submit(geocode_postal, pc): pc for pc in todo}
        try:
            for fut in as_completed(futures):
                completed += 1
                if completed % ONEMAP_SAVE_EVERY == 0 or completed == total:
                    save_postal_cache()
                    elapsed = time.time() - t0
                    rate = completed / elapsed if elapsed else 0
                    eta = (total - completed) / rate if rate else 0
                    print(f"  [{completed}/{total}]  {rate:.1f}/s  "
                          f"ETA {eta/60:.1f} min", flush=True)
        except KeyboardInterrupt:
            print("\n  Interrupted. Saving cache...", flush=True)
            save_postal_cache()
            raise

    save_postal_cache()


# ---------- Repair phase: address fallback ----------

def find_missing(index, done):
    """Return list of (entry, parsed, address) for records with no coords."""
    missing = []
    for entry in index:
        url = entry.get("profile_url")
        parsed = done.get(url, {}) or {}
        pc = pick_postal(entry, parsed)
        with _geocode_lock:
            cached = _postal_cache.get(pc) if pc else None
        if cached and cached.get("lat") is not None:
            continue
        addr = pick_address(entry, parsed)
        if addr:
            with _geocode_lock:
                acached = _postal_cache.get(ADDR_PREFIX + addr)
            if acached and acached.get("lat") is not None:
                continue
        missing.append((entry, parsed, addr))
    return missing


def repair_phase(index, done):
    """Retry any record still missing coords via address search."""
    missing = find_missing(index, done)

    if not missing:
        print("Repair: nothing missing, all records have coords.", flush=True)
        return

    print(f"Repair: {len(missing)} records still missing coords. "
          f"Trying address fallback ({REPAIR_WORKERS} workers)...",
          flush=True)

    completed = 0
    fixed = 0
    t0 = time.time()
    total = len(missing)

    def _try(addr):
        if not addr:
            return None
        return geocode_address(addr)

    with ThreadPoolExecutor(max_workers=REPAIR_WORKERS) as pool:
        futures = {pool.submit(_try, addr): (entry, parsed, addr)
                   for entry, parsed, addr in missing}
        try:
            for fut in as_completed(futures):
                completed += 1
                try:
                    lat, lng = fut.result() or (None, None)
                except Exception:
                    lat, lng = None, None
                if lat is not None:
                    fixed += 1

                if completed % REPAIR_SAVE_EVERY == 0 or completed == total:
                    save_postal_cache()
                    elapsed = time.time() - t0
                    rate = completed / elapsed if elapsed else 0
                    eta = (total - completed) / rate if rate else 0
                    print(f"  [{completed}/{total}]  fixed {fixed}  "
                          f"{rate:.1f}/s  ETA {eta/60:.1f} min", flush=True)
        except KeyboardInterrupt:
            print("\n  Interrupted. Saving cache...", flush=True)
            save_postal_cache()
            raise

    save_postal_cache()
    print(f"Repair: fixed {fixed}/{total} via address fallback.", flush=True)


# ---------- progress ----------

def load_index():
    if not INPUT.exists():
        raise SystemExit(f"Missing {INPUT}. Run halal_data_scrape.py first.")
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"{INPUT} is not a JSON list.")
    return data


def load_progress():
    if not PROGRESS.exists():
        return {}
    try:
        saved = json.loads(PROGRESS.read_text(encoding="utf-8"))
        return saved.get("done", {})
    except (json.JSONDecodeError, OSError):
        return {}


def save_progress(done):
    with _lock:
        PROGRESS.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS.write_text(
            json.dumps({"done": done}, ensure_ascii=False),
            encoding="utf-8",
        )


# ---------- output ----------

def _lookup_coords(pc, addr):
    """Look up coords in the cache — postal first, then address."""
    with _geocode_lock:
        if pc:
            cached = _postal_cache.get(pc)
            if cached and cached.get("lat") is not None:
                return cached.get("lat"), cached.get("lng")
        if addr:
            cached = _postal_cache.get(ADDR_PREFIX + addr)
            if cached and cached.get("lat") is not None:
                return cached.get("lat"), cached.get("lng")
    return None, None


def build_output(index, done):
    """Combine index + parsed profile + cached coords into final records."""
    results = []
    for entry in index:
        url = entry.get("profile_url")
        parsed = done.get(url, {}) or {}

        raw_index = entry.get("postal_code", "") or ""
        raw_page = parsed.get("postal_code_from_page", "") or ""
        pc = pick_postal(entry, parsed)
        addr = pick_address(entry, parsed)

        lat, lng = _lookup_coords(pc, addr)

        results.append({
            "name": entry.get("name", ""),
            "halal_status": entry.get("halal_status", "Certified"),
            "postal_code": pc,
            "postal_code_index": normalize_postal(raw_index),
            "postal_code_page": normalize_postal(raw_page),
            "cert_no": parsed.get("cert_no", ""),
            "scheme": parsed.get("scheme", ""),
            "category": parsed.get("category", ""),
            "address": parsed.get("address", ""),
            "planning_area": parsed.get("planning_area", ""),
            "register_date": parsed.get("register_date", ""),
            "latitude": lat,
            "longitude": lng,
        })
    return results


# ---------- main ----------

def main():
    index = load_index()
    print(f"Loaded {len(index)} entries from {INPUT}", flush=True)

    load_postal_cache()
    print(f"Postal cache: {len(_postal_cache)} codes loaded", flush=True)

    done = load_progress()
    if done:
        print(f"Resuming: {len(done)} profiles already fetched.", flush=True)

    try:
        fetch_phase(index, done)
    except KeyboardInterrupt:
        print("Stopped during phase 1. Cache saved; re-run to resume.",
              flush=True)
        return

    try:
        geocode_phase(index, done)
    except KeyboardInterrupt:
        print("Stopped during phase 2. Cache saved; re-run to resume.",
              flush=True)
        return

    try:
        repair_phase(index, done)
    except KeyboardInterrupt:
        print("Stopped during repair. Cache saved; re-run to resume.",
              flush=True)
        return

    results = build_output(index, done)
    results.sort(key=lambda r: r["name"].lower())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if PROGRESS.exists():
        PROGRESS.unlink()

    with_cert = sum(1 for r in results if r["cert_no"])
    with_addr = sum(1 for r in results if r["address"])
    with_geo = sum(1 for r in results if r["latitude"] is not None)
    print(f"\nDone.", flush=True)
    print(f"  Total:        {len(results)}", flush=True)
    print(f"  With cert #:  {with_cert}", flush=True)
    print(f"  With address: {with_addr}", flush=True)
    print(f"  With coords:  {with_geo}", flush=True)
    print(f"  Saved to:     {OUTPUT}", flush=True)


if __name__ == "__main__":
    main()