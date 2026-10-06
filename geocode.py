
import json
from pathlib import Path
import requests

# 1. Geocode the two stragglers directly via OneMap.
CACHE = Path("data/onemap_postal_cache.json")
cache = json.loads(CACHE.read_text())

for pc in ["238872", "169608"]:
    if pc in cache and cache[pc].get("lat") is not None:
        print(f"{pc}: already cached")
        continue
    r = requests.get(
        "https://www.onemap.gov.sg/api/common/elastic/search",
        params={"searchVal": pc, "returnGeom": "Y",
                "getAddrDetails": "Y", "pageNum": 1},
        timeout=15,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("found", 0) > 0:
        r0 = d["results"][0]
        cache[pc] = {"lat": float(r0["LATITUDE"]),
                     "lng": float(r0["LONGITUDE"])}
        print(f"{pc}: cached {cache[pc]}")
    else:
        cache[pc] = {"lat": None, "lng": None}
        print(f"{pc}: no match")

CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

# 2. Patch the output JSON so those 4 records get coords.
OUT = Path("data/HalalFreak_certified.json")
out = json.loads(OUT.read_text())
patched = 0
for rec in out:
    if rec["latitude"] is None and rec["postal_code"] in cache:
        entry = cache[rec["postal_code"]]
        if entry.get("lat") is not None:
            rec["latitude"]  = entry["lat"]
            rec["longitude"] = entry["lng"]
            patched += 1
            print(f"  patched: {rec['name']!r}")

OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))

with_geo = sum(1 for r in out if r["latitude"] is not None)
print(f"\npatched {patched} records")
print(f"with coords: {with_geo}/{len(out)}")
