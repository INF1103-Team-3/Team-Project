"""Logic layer — business rules applied to the AI-enriched record."""
from datetime import datetime
import config
from io_manager import BAND_SYMBOLS

ALLOWED_DIETARY = {
    "none": {"none", "vegetarian", "vegan", "halal"},
    "halal": {"halal"},
    "vegetarian": {"vegetarian", "vegan"},
    "vegan": {"vegan"},
}

BAND_ORDER = ["inexpensive", "moderate", "expensive", "very_expensive"]
BAND_LOW = {"inexpensive": 0.0, "moderate": 8.0, "expensive": 15.0, "very_expensive": 30.0}


def _band_index(band):
    return BAND_ORDER.index(band) if band in BAND_ORDER else -1


def _cheapest_price(r):
    """Best available price signal: exact catalog price, then range start, then range end."""
    if r.get("avg_price") is not None:
        return r["avg_price"]
    if r.get("price_start") is not None:
        return r["price_start"]
    if r.get("price_end") is not None:
        return r["price_end"]
    return None


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


_GOOGLE_DAY = {"monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4,
               "friday": 5, "saturday": 6, "sunday": 0}


def _resolve_open_hours(restaurant, req):
    """Returns the HH:MM-HH:MM window for the requested day (or today).
    Catalog open_hours wins; Google weekly_hours (requested day) is fallback."""
    eat_day = (req.get("eat_day") or "today").lower()
    if eat_day != "today":
        gday = _GOOGLE_DAY.get(eat_day)
        weekly = restaurant.get("weekly_hours") or {}
        if gday is not None and gday in weekly:
            return weekly[gday], eat_day
        return None, eat_day
    # today: catalog hours are already today's; else Google's index for today
    hours = restaurant.get("open_hours")
    if hours:
        return hours, "today"
    weekly = restaurant.get("weekly_hours") or {}
    today_gday = (datetime.now().weekday() + 1) % 7   # Mon=0 -> Google Sun=0
    if today_gday in weekly:
        return weekly[today_gday], "today"
    return None, "today"

def open_status(restaurant, req):
    """'open' | 'closed' | 'unknown' for the requested day/time. Never invents."""
    eat_time = req.get("eat_time", "now")
    hours, _ = _resolve_open_hours(restaurant, req)
    if not hours or "-" not in hours:
        return "unknown"
    start_s, end_s = hours.split("-")
    start, end = _minutes(start_s), _minutes(end_s)
    if eat_time == "now":
        now = datetime.now()
        t = now.hour * 60 + now.minute
    else:
        try:
            t = _minutes(eat_time)
        except (ValueError, AttributeError):
            return "unknown"
    return "open" if start <= t <= end else "closed"


def decide_outcome(restaurant, req):
    """MULTI-CONDITION RULE using AI output fields.

    Outcomes:
      'match'       -> all hard rules pass; scored on preferences.
      'alternative' -> shown with verified positives ('+'), disqualifiers
                       ('!') and honest unknowns ('!'): dietary/allergen
                       unverifiable, budget over max, travel over limit,
                       or a requested field unverifiable.
      'reject'      -> hard-failed (verified dietary conflict, verified
                       allergen overlap, rating below minimum) -> hidden.
    Reasons are tagged here; display prints them verbatim."""
    reasons = []    # positive reasons (why it's interesting)
    problems = []   # disqualifiers (why it is not a match right now)
    notes = []      # informational, does NOT demote a match
    unverified = []  # requested field unverifiable -> demotes to alternative

    # ---------- HARD RULE 1: dietary ----------
    wanted = (req.get("dietary") or "none").lower()
    r_dietary = restaurant.get("dietary", "none")
    if r_dietary == "unknown":
        if wanted != "none":
            unverified.append("dietary certification unknown — please confirm with the restaurant")
    elif r_dietary not in ALLOWED_DIETARY[wanted]:
        return "reject", 0, ["dietary requirement not met"]

    # ---------- HARD RULE 2: allergies ----------
    wanted_allergies = {a.lower() for a in (req.get("allergies") or [])}
    if wanted_allergies:
        allergens = restaurant.get("allergens")
        if allergens is None:
            unverified.append("ingredient information unavailable — cannot verify your allergies")
        else:
            overlap = wanted_allergies & {a.lower() for a in allergens}
            if overlap:
                return "reject", 0, [f"contains allergen(s): {', '.join(sorted(overlap))} "
                                     "(confirm with restaurant — never assumed allergy-safe)"]

    # ---------- HARD RULE 3: rating (verified-below-minimum -> hidden) ----------
    min_rating = req.get("min_rating")
    rating = restaurant.get("rating")
    if min_rating is not None and rating is not None and rating < min_rating:
        return "reject", 0, [f"rating {rating} is below your {min_rating} minimum"]

    # ---------- BUDGET: dollar-max mode or band mode ----------
    wanted_band = req.get("budget_band")
    bmin, bmax = req.get("budget_min"), req.get("budget_max")
    r_band = restaurant.get("price_band")
    cheapest = _cheapest_price(restaurant)
    has_price_signal = cheapest is not None or r_band is not None

    if bmax is not None:
        if cheapest is not None and cheapest > bmax:
            problems.append(f"cheapest items around ${cheapest:.0f} "
                            f"exceed your ${bmax:.0f} max")
        elif r_band is not None and BAND_LOW.get(r_band, 0.0) > bmax:
            problems.append(f"price band {BAND_SYMBOLS[r_band]} starts "
                            f"above your ${bmax:.0f} max")
    elif wanted_band and r_band is not None:
        if _band_index(r_band) > _band_index(wanted_band):
            problems.append(f"price band {BAND_SYMBOLS[r_band]} exceeds "
                            f"your {BAND_SYMBOLS[wanted_band]} budget")

    # ---------- TRAVEL (chosen mode only; other mode is display info) ----------
    mode = req.get("mode", "walk")
    if mode == "drive":
        km_limit = req.get("max_drive_km")
        d_meters = restaurant.get("drive_meters")
        if km_limit is not None and d_meters is not None:
            if (d_meters / 1000) > km_limit:
                problems.append(f"would be a {d_meters / 1000:.1f} km drive, "
                                f"over your {km_limit:.0f} km limit")
        travel_unknown = (km_limit is not None and d_meters is None)
    else:
        walk_limit = req.get("max_walk_minutes")
        w_minutes = restaurant.get("walk_minutes")
        if walk_limit is not None and w_minutes is not None and w_minutes > walk_limit:
            problems.append(f"would need to walk {w_minutes - walk_limit} more minutes")
        travel_unknown = (walk_limit is not None and w_minutes is None)

    # ---------- UNVERIFIABLE REQUESTED FIELDS (demote to alternative) ----------
    if bmax is not None and not has_price_signal:
        unverified.append(f"price unavailable — cannot verify your ${bmax:.0f} max")
    if bmax is None and wanted_band and r_band is None:
        unverified.append("price band unavailable — cannot verify budget")
    if travel_unknown:
        unverified.append("travel time unavailable — cannot verify distance")
    if min_rating is not None and rating is None:
        unverified.append("rating unavailable — cannot verify quality")

    # ---------- PREFERENCES (scored for matches, listed for alternatives too) ----------
    score = 0
    cuisine = (req.get("cuisine") or "any").lower()
    if cuisine not in ("any", "") and cuisine in (restaurant.get("cuisine") or "").lower():
        score += 3
        reasons.append("matches your cuisine preference")
    if bmax is not None and cheapest is not None:
        if bmin is not None and bmin <= cheapest <= bmax:
            score += 1
            reasons.append(f"right in your ${bmin:.0f}-{bmax:.0f} range")
        elif bmin is None and cheapest <= bmax * 0.7:
            score += 1
            reasons.append("well within budget")
    elif wanted_band and r_band is not None and _band_index(r_band) < _band_index(wanted_band):
        score += 1
        reasons.append(f"cheaper than your {BAND_SYMBOLS[wanted_band]} budget")
    if rating is not None and rating >= 4.5:
        score += 1
        reasons.append("highly rated (4.5+)")
    status = open_status(restaurant, req)
    if status == "open":
        score += 1
        reasons.append("open at your requested time")
    elif status == "unknown":
        notes.append("opening hours unknown — please confirm with the restaurant")
    else:
        score -= 1
        reasons.append("likely closed at your requested time")
    if "spicy" in (req.get("free_text_notes") or "").lower() and restaurant.get("spicy_options"):
        score += 1
        reasons.append("has spicy options")

    # ---------- OUTCOME ----------
    if problems or unverified:
        return "alternative", 0, (reasons
                                  + [f"! {p}" for p in problems]
                                  + [f"! {u}" for u in unverified])
    if not reasons and not notes:
        reasons.append("meets all your hard requirements")
    return "match", score, reasons + [f"! {n}" for n in notes]

def rank_restaurants(restaurants, req):
    matches, alternatives = [], []
    hidden = 0
    for r in restaurants:
        status, score, reasons = decide_outcome(r, req)
        if status == "match":
            matches.append({"restaurant": r, "score": score, "reasons": reasons})
        elif status == "alternative":
            alternatives.append({"restaurant": r, "score": 0, "reasons": reasons})
        else:
            hidden += 1
    matches.sort(key=lambda x: x["score"], reverse=True)
    return {"matches": matches[:config.MAX_MATCHES_SHOWN],
            "alternatives": alternatives[:config.MAX_ALTERNATIVES_SHOWN],
            "hidden": hidden,
            "mode": req.get("mode", "walk")}
