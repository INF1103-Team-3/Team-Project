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


def _cuisine_matches(wanted, restaurant_cuisines):
    w = (wanted or "").strip().lower()
    if w in ("", "any"):
        return True
    for rc in restaurant_cuisines or []:
        rc = (rc or "").lower()
        if not rc:
            continue
        if w == rc or w in rc or rc in w:
            return True
    return False


def _restaurant_cuisines(r):
    lst = r.get("cuisines")
    if isinstance(lst, list) and lst:
        return lst
    single = r.get("cuisine")
    return [single] if single else []


def open_status(restaurant, eat_time):
    """Return 'open', 'closed', or 'unknown' for the given time.

    Reads restaurant['weekday_hours']:
      {"monday": ["1100", "2330"], "tuesday": [], "wednesday": None, ...}
      [] = closed, None = unknown, ["0000", "2359"] = 24 hours.
    """
    wh = restaurant.get("weekday_hours")
    if not wh:
        return "unknown"

    now = datetime.now()
    weekday = now.strftime("%A").lower()

    if eat_time == "now":
        current = now.hour * 60 + now.minute
    else:
        try:
            h, m = eat_time.split(":")
            current = int(h) * 60 + int(m)
        except (ValueError, AttributeError):
            return "unknown"

    day_hours = wh.get(weekday)
    if day_hours is None:
        return "unknown"
    if not day_hours:
        return "closed"

    try:
        open_m = int(day_hours[0][:2]) * 60 + int(day_hours[0][2:])
        close_m = int(day_hours[1][:2]) * 60 + int(day_hours[1][2:])
    except (IndexError, ValueError, TypeError):
        return "unknown"

    # 24-hour case
    if day_hours == ["0000", "2359"]:
        return "open"

    # Overnight (closes next day, e.g. 22:00 → 02:00)
    if close_m < open_m:
        if current >= open_m or current <= close_m:
            return "open"
        return "closed"

    return "open" if open_m <= current <= close_m else "closed"


def decide_outcome(restaurant, req):
    """MULTI-CONDITION RULE using AI output fields."""
    reasons = []

    # --- HARD RULE 1: dietary ---
    wanted = (req.get("dietary") or "none").lower()
    r_dietary = restaurant.get("dietary", "none")
    halal_flag = restaurant.get("halal_certified")

    if wanted == "halal":
        if halal_flag is True or r_dietary == "halal":
            pass
        elif halal_flag is None and r_dietary == "unknown":
            return "alternative", 0, ["halal certification not verified — "
                                      "please confirm with the restaurant"]
        else:
            return "reject", 0, ["not halal certified"]
    else:
        if r_dietary == "unknown":
            if wanted != "none":
                return "alternative", 0, ["dietary certification unknown — "
                                          "please confirm with the restaurant"]
        elif r_dietary not in ALLOWED_DIETARY[wanted]:
            return "reject", 0, ["dietary requirement not met"]

    # --- HARD RULE 2: allergies ---
    wanted_allergies = {a.lower() for a in (req.get("allergies") or [])}
    if wanted_allergies:
        allergens = restaurant.get("allergens")
        if allergens is None:
            return "alternative", 0, ["ingredient information unavailable — cannot verify your allergies"]
        overlap = wanted_allergies & {a.lower() for a in allergens}
        if overlap:
            return "reject", 0, [f"contains allergen(s): {', '.join(sorted(overlap))} "
                                 "(confirm with restaurant — never assumed allergy-safe)"]

    # --- HARD RULE 3: rating ---
    min_rating = req.get("min_rating")
    rating = restaurant.get("rating")
    if min_rating is not None and rating is not None and rating < min_rating:
        return "reject", 0, [f"rating {rating} is below your {min_rating} minimum"]

    # --- BUDGET ---
    wanted_band = req.get("budget_band")
    if wanted_band == "any":
        wanted_band = None
    bmin, bmax = req.get("budget_min"), req.get("budget_max")
    r_band = restaurant.get("price_band")
    cheapest = _cheapest_price(restaurant)
    price_verified = False

    if bmax is not None:
        if cheapest is not None:
            price_verified = True
            if cheapest > bmax:
                return "alternative", 0, [f"cheapest items around ${cheapest:.0f} "
                                          f"exceed your ${bmax:.0f} max"]
        elif r_band is not None:
            if BAND_LOW.get(r_band, 0.0) > bmax:
                return "alternative", 0, [f"price band {BAND_SYMBOLS[r_band]} starts "
                                          f"above your ${bmax:.0f} max"]
            price_verified = True
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

    # --- UNVERIFIABLE DATA ---
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

    # --- CUISINE ---
    wanted_cuisine = (req.get("cuisine") or "any").strip().lower()
    restaurant_cuisines = _restaurant_cuisines(restaurant)

    if wanted_cuisine not in ("any", "") and not _cuisine_matches(wanted_cuisine,
                                                                  restaurant_cuisines):
        listed = ", ".join(restaurant_cuisines) or "unknown"
        return "alternative", 0, [f"cuisine is {listed}, not {req.get('cuisine')}"]

    # --- PREFERENCES (scoring) ---
    score = 0
    if wanted_cuisine not in ("any", "") and _cuisine_matches(wanted_cuisine,
                                                              restaurant_cuisines):
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
    matches.sort(key=lambda item: item["score"], reverse=True)
    return {"matches": matches[:config.MAX_MATCHES_SHOWN],
            "alternatives": alternatives[:config.MAX_ALTERNATIVES_SHOWN],
            "hidden": hidden}