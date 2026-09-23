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
# lower bounds of each band, in SG dollars (mirror of data_manager.BAND_THRESHOLDS)
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


def open_status(restaurant, eat_time):
    hours = restaurant.get("open_hours")
    if not hours or "-" not in hours:
        return "unknown"
    start, end = (_minutes(s.strip()) for s in hours.split("-"))
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
    Hard rules (dietary, allergies, verified-low rating, budget_max exceeded)
    -> reject/hidden. Relaxable (band budget, walk) -> alternative.
    Unverifiable unknowns -> alternative. Otherwise scored match."""
    reasons = []

    # --- HARD RULE 1: dietary (never relaxed) ---
    wanted = (req.get("dietary") or "none").lower()
    r_dietary = restaurant.get("dietary", "none")
    if r_dietary == "unknown":
        if wanted != "none":
            return "alternative", 0, ["dietary certification unknown — please confirm with the restaurant"]
    elif r_dietary not in ALLOWED_DIETARY[wanted]:
        return "reject", 0, ["dietary requirement not met"]

    # --- HARD RULE 2: allergies (never relaxed) ---
    wanted_allergies = {a.lower() for a in (req.get("allergies") or [])}
    if wanted_allergies:
        allergens = restaurant.get("allergens")
        if allergens is None:
            return "alternative", 0, ["ingredient information unavailable — cannot verify your allergies"]
        overlap = wanted_allergies & {a.lower() for a in allergens}
        if overlap:
            return "reject", 0, [f"contains allergen(s): {', '.join(sorted(overlap))} "
                                 "(confirm with restaurant — never assumed allergy-safe)"]

    # --- HARD RULE 3: verified rating below user's minimum -> hidden entirely ---
    min_rating = req.get("min_rating")
    rating = restaurant.get("rating")
    if min_rating is not None and rating is not None and rating < min_rating:
        return "reject", 0, [f"rating {rating} is below your {min_rating} minimum"]

    # --- BUDGET: exact-dollar mode (budget_max) or band mode ---
    wanted_band = req.get("budget_band")
    bmin, bmax = req.get("budget_min"), req.get("budget_max")
    r_band = restaurant.get("price_band")
    cheapest = _cheapest_price(restaurant)
    price_verified = False

    if bmax is not None:
        # exact-dollar budget: the "not exceeding" rule
        if cheapest is not None:
            price_verified = True
            if cheapest > bmax:
                return "alternative", 0, [f"cheapest items around ${cheapest:.0f} "
                                          f"exceed your ${bmax:.0f} max"]
        elif r_band is not None:
            if BAND_LOW.get(r_band, 0.0) > bmax:
                return "alternative", 0, [f"price band {BAND_SYMBOLS[r_band]} starts "
                                          f"above your ${bmax:.0f} max"]
            price_verified = True   # band starts at/below max: optimistically fits
        # else: no price signal at all -> unknowns section below
    elif wanted_band and r_band is not None:
        price_verified = True
        if _band_index(r_band) > _band_index(wanted_band):
            return "alternative", 0, [f"price band {BAND_SYMBOLS[r_band]} exceeds "
                                      f"your {BAND_SYMBOLS[wanted_band]} budget"]

    # --- RELAXABLE: walking time ---
    r_walk = restaurant.get("walk_minutes")
    walk = req.get("max_walk_minutes")
    if walk is not None and r_walk is not None and r_walk > walk:
        return "alternative", 0, [f"would need to walk {r_walk - walk} more minutes"]

    # --- UNVERIFIABLE DATA (relevant unknowns -> alternative, shown as unavailable) ---
    unknowns = []
    if bmax is not None and not price_verified:
        unknowns.append(f"price unavailable — cannot verify your ${bmax:.0f} max")
    if bmax is None and wanted_band and r_band is None:
        unknowns.append("price band unavailable — cannot verify budget")
    if walk is not None and r_walk is None:
        unknowns.append("walking time unavailable — cannot verify distance")
    if min_rating is not None and rating is None:
        unknowns.append("rating unavailable — cannot verify quality")
    if unknowns:
        return "alternative", 0, unknowns

    # --- PREFERENCES (only scored after all rules pass) ---
    score = 0
    cuisine = (req.get("cuisine") or "any").lower()
    if cuisine not in ("any", "") and cuisine in (restaurant.get("cuisine") or "").lower():
        score += 3
        reasons.append("matches your cuisine preference")
    if bmax is not None and cheapest is not None:
        if bmin is not None and bmin <= cheapest <= bmax:
            score += 1
            reasons.append(f"right in your ${bmin:.0f}–${bmax:.0f} range")
        elif bmin is None and cheapest <= bmax * 0.7:
            score += 1
            reasons.append("well within budget")
    elif wanted_band and r_band is not None and _band_index(r_band) < _band_index(wanted_band):
        score += 1
        reasons.append(f"cheaper than your {BAND_SYMBOLS[wanted_band]} budget")
    if rating is not None and rating >= 4.5:
        score += 1
        reasons.append("highly rated (4.5+)")
    status = open_status(restaurant, req.get("eat_time", "now"))
    if status == "open":
        score += 1
        reasons.append("open at your requested time")
    elif status == "unknown":
        reasons.append("opening hours unknown — please confirm with the restaurant")
    else:
        score -= 1
        reasons.append("likely closed at your requested time")
    if "spicy" in (req.get("free_text_notes") or "").lower() and restaurant.get("spicy_options"):
        score += 1
        reasons.append("has spicy options")
    if not reasons:
        reasons.append("meets all your hard requirements")
    return "match", score, reasons


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
            "hidden": hidden}
