"""Shared account and preference contract; no IO or persistence."""

import math
import re

from common.singapore_locations import (
    extract_postal_digits,
    validate_location_syntax,
)

OTHER_PREFERENCES = "other_preferences"
PREFERENCE_FIELDS = (
    "location",
    "max_distance_km",
    "max_travel_time_minutes",
    "budget_per_person",
    "dietary_requirements",
    "liked_cuisines",
    "disliked_cuisines",
    OTHER_PREFERENCES,
)
USER_FIELDS = {"userID", "email", "email_verified", "username", "preferences"}
CUISINES = (
    "chinese",
    "malay",
    "indian",
    "peranakan",
    "indonesian",
    "thai",
    "vietnamese",
    "filipino",
    "japanese",
    "korean",
    "western",
    "italian",
    "french",
    "american",
    "mexican",
    "turkish",
    "middle eastern",
    "mediterranean",
    "fusion",
    "lebanese",
)
DIETARY_CHOICES = ("halal", "vegetarian")
CUISINE_FIELDS = ("liked_cuisines", "disliked_cuisines")
NUMBER_LIMITS = {
    "max_distance_km": (0.01, 100),
    "max_travel_time_minutes": (0.1, 2000),
    "budget_per_person": (0.01, 1000),
}
PROFILE_NUMBER_LIMITS = {
    "max_distance_km": (0.01, 50.0),
    "max_travel_time_minutes": (1.0, 150.0),
    "budget_per_person": (0.01, 1000.0),
}
SEARCH_MODE_LIMITS = {
    "walk": {
        "max_distance_km": (0.01, 15.0),
        "max_travel_minutes": (1.0, 90.0),
    },
    "drive": {
        "max_distance_km": (0.01, 50.0),
        "max_travel_minutes": (1.0, 120.0),
    },
    "transit": {
        "max_distance_km": (0.01, 50.0),
        "max_travel_minutes": (1.0, 150.0),
    },
}
MINUTES_PER_KM = 20
TRANSIT_MINUTES_RANGE = (1, 150)
_COORDINATE_TEXT = re.compile(
    r"^\s*[+-]?\d+(?:\.\d+)?\s*,\s*[+-]?\d+(?:\.\d+)?\s*$"
)
_WISH_ALLOWED_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ,.'!?/&()+\-=>]*")
_DECIMAL_SPACE_RX = re.compile(r"\b(\d+)\s*\.\s*(\d+)\b")
_RATING_WISH_RX = re.compile(
    (
        "(?:\\b(?:minimum|min\\.?|at least|no less "
        "than|above|over)\\b|>=?)\\s*(?:google\\s*)?(?:(?:rating|rated)\\s*(?:"
        "of\\s*|is\\s*)?(\\d+(?:\\.\\d+)?|\\.\\d+)(?:\\s*(?:\\+\\s*)?(?:stars?"
        "|/\\s*5|\\+))?|(\\d+(?:\\.\\d+)?|\\.\\d+)\\s*(?:\\+\\s*)?(?:stars?|/"
        "\\s*5|rating\\b|rated\\b))|\\b(?:google\\s*)?(?:rating|rated)\\s*(?:o"
        "f\\s*|is\\s*)?(?:>=?|at least|minimum|min\\.?|no less "
        "than|above|over)?\\s*(\\d+(?:\\.\\d+)?|\\.\\d+)(?:\\s*(?:\\+\\s*)?(?:"
        "stars?|/\\s*5)|\\s*\\+(?!\\w)|(?=[,.;!?\\s]|$))|\\b(\\d+(?:\\.\\d+)?|"
        "\\.\\d+)\\s*(?:\\+\\s*)?(?:stars?|/\\s*5)(?!\\w)(?:\\s*(?:or "
        "higher|or above|and up|or better|minimum|min\\.?|\\+)(?!\\w))?|\\b(\\"
        "d+(?:\\.\\d+)?|\\.\\d+)\\s*(?:\\+\\s*)?(?:rating|rated)\\b(?:\\s*(?:o"
        "r higher|or above|and up|or better|minimum|min\\.?|\\+)(?!\\w))?"
    ),
    re.IGNORECASE,
)
_WISH_ACRONYMS = {
    "bbq",
    "byob",
    "msg",
    "cbd",
    "mrt",
    "hrs",
    "gym",
    "nth",
    "sgd",
    "ac",
    "tv",
    "vip",
    "wfh",
}
_WISH_KEYBOARD_MASH = (
    "asdf",
    "sdfg",
    "dfgh",
    "fghj",
    "ghjk",
    "hjkl",
    "qwer",
    "wert",
    "qwrt",
    "erty",
    "tyui",
    "uiop",
    "zxcv",
    "xcvb",
    "cvbn",
    "vbnm",
)
_CUISINE_TEXT_RX = re.compile(r"[a-z]+(?:[ '\-&/][a-z]+)*")
_CUISINE_SUFFIX_RX = re.compile(r"\s+cuisines?$", re.IGNORECASE)
_CUISINE_ACRONYMS = frozenset({"bbq", "kbbq"})
_INVALID_CUISINE_WORDS = frozenset(
    {
        "none",
        "any",
        "all",
        "nothing",
        "something",
        "anything",
        "whatever",
        "random",
        "stuff",
        "thing",
        "things",
        "test",
        "testing",
        "hello",
        "hi",
        "hey",
        "bye",
        "ok",
        "okay",
        "yes",
        "no",
        "maybe",
        "null",
        "undefined",
        "nan",
        "blorp",
        "foobar",
        "foo",
        "bar",
        "baz",
        "xyz",
        "abc",
        "qwerty",
        "food",
        "foods",
        "cuisine",
        "cuisines",
        "restaurant",
        "restaurants",
        "meal",
        "meals",
        "dish",
        "dishes",
        "eat",
        "eating",
        "lol",
        "lmao",
        "lmfao",
        "rofl",
        "wtf",
        "wth",
        "omg",
        "omfg",
        "idk",
        "imo",
        "tbh",
        "brb",
        "yolo",
        "fomo",
        "uwu",
        "owo",
        "sus",
        "yeet",
        "bruh",
        "bro",
        "sis",
        "idiot",
        "stupid",
        "dumb",
        "moron",
        "retard",
        "loser",
        "clown",
        "trash",
        "garbage",
        "rubbish",
        "nonsense",
        "gibberish",
        "poop",
        "fart",
        "cb",
        "ccb",
        "knn",
        "knnb",
        "knnbccb",
        "lampa",
        "lanjiao",
        "lj",
        "cheebai",
        "chibai",
        "kanina",
        "nabei",
        "limpeh",
        "pukimak",
        "kontol",
        "babi",
        "anjing",
        "bodoh",
        "sial",
        "cibai",
        "fuck",
        "fucking",
        "shit",
        "bitch",
        "ass",
        "asshole",
        "dick",
        "cock",
        "pussy",
        "cunt",
        "bastard",
        "whore",
        "slut",
        "damn",
        "crap",
        "hell",
        "suck",
        "porn",
        "sex",
    }
)
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)


def empty_preferences():
    """Null means unanswered; an empty list means explicitly none."""
    return dict.fromkeys(PREFERENCE_FIELDS)


def clean_text(value, maximum=200, allow_empty=False):
    """Validate strings without guessing, coercing, or truncating."""
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError("Enter text without control characters.")
    value = value.strip()
    if not value and allow_empty:
        return ""
    if (
        not value
        or len(value) > maximum
        or not any(c.isalnum() for c in value)
    ):
        raise ValueError(f"Enter 1–{maximum} characters of meaningful text.")
    return value


def normalize_username(value):
    """The account display name is separate from preferences."""
    return clean_text(value, 50)


def normalize_email(value):
    """Normalize email for unique lookup and validate practical syntax."""
    if not isinstance(value, str):
        raise ValueError("Enter a valid email address.")
    value = value.strip().lower()
    if len(value) > 254 or not EMAIL_PATTERN.fullmatch(value):
        raise ValueError("Enter a valid email address.")
    local = value.split("@", 1)[0]
    if len(local) > 64 or local.startswith(".") or local.endswith("."):
        raise ValueError("Enter a valid email address.")
    if ".." in local:
        raise ValueError("Enter a valid email address.")
    return value


def normalize_wish_text(value):
    """Collapse spacing and rejoin split decimal numbers such as '4 .5' ->
    '4.5'.
    """
    collapsed = " ".join(str(value or "").strip().split())
    return _DECIMAL_SPACE_RX.sub(r"\1.\2", collapsed)


def extract_rating_wishes(text):
    """Return numeric star ratings found in a special-request string
    (validating 1..5).
    """
    normalized = normalize_wish_text(text)
    values = []
    for match in _RATING_WISH_RX.finditer(normalized):
        raw = next((g for g in match.groups() if g is not None), None)
        if raw is None:
            continue
        rating = float(raw)
        if not 1.0 <= rating <= 5.0:
            raise ValueError(
                "Google star ratings must be between 1 and 5 stars."
            )
        values.append(rating)
    return values


def strip_rating_clauses(text):
    """Remove valid Google star rating clauses, preserving other wish text."""
    normalized = normalize_wish_text(text)
    remainder = _RATING_WISH_RX.sub(" ", normalized)
    remainder = re.sub(
        r"^(?:\s*(?:and|with|&|,|/)\b\s*)+", "", remainder, flags=re.IGNORECASE
    )
    remainder = re.sub(
        r"(?:\s*\b(?:and|with)\s*|\s*[,&/]\s*)+$",
        "",
        remainder,
        flags=re.IGNORECASE,
    )
    remainder = re.sub(r"\s{2,}", " ", remainder).strip(" ,;-/")
    return remainder


def normalize_list(
    value,
    choices=None,
    required=False,
    allow_coordinates=False,
    allow_ratings=False,
):
    """Require lists and keep all entries or reject the entire answer."""
    if not isinstance(value, list):
        raise ValueError("Expected a list of text entries.")
    result = []
    for item in value:
        item = clean_text(
            normalize_wish_text(item) if allow_ratings else item, 100
        ).lower()
        has_rating = bool(allow_ratings and extract_rating_wishes(item))
        has_sg_postal = bool(
            allow_coordinates and extract_postal_digits(item) is not None
        )
        if (
            not any(c.isalpha() for c in item)
            and not (allow_coordinates and _COORDINATE_TEXT.fullmatch(item))
            and not has_rating
            and not has_sg_postal
        ):
            raise ValueError("List entries must contain letters.")
        if choices is not None and item not in choices:
            raise ValueError("Choose from: " + ", ".join(choices) + ".")
        if item not in result:
            result.append(item)
    if required and not result:
        raise ValueError("Enter at least one location.")
    return result


def validate_english_preferences(items, field_label="Special requests"):
    """Require proper meaningful English text and valid 1..5 star wishes."""
    normalized_items = []
    for item in items:
        text = normalize_wish_text(item)
        if not text:
            continue
        if len(text) > 100 or not _WISH_ALLOWED_TEXT.fullmatch(text):
            raise ValueError(
                f"{field_label} must use proper English letters and words "
                "(e.g. quiet seating, spicy food)."
            )
        try:
            ratings = extract_rating_wishes(text)
        except ValueError as err:
            raise ValueError(f"{field_label}: {err}") from err
        remainder = strip_rating_clauses(text)
        if ratings and not remainder:
            normalized_items.append(text)
            continue
        check_text = remainder or text
        words = re.findall(r"[A-Za-z]+", check_text)
        if not words or not any(len(word) > 1 for word in words):
            raise ValueError(
                f"{field_label} must contain meaningful English words "
                "(e.g. quiet seating, spicy food)."
            )
        for word in words:
            low = word.lower()
            if (
                re.search(r"(.)\1\1", low)
                or any(seq in low for seq in _WISH_KEYBOARD_MASH)
                or (
                    len(low) >= 3
                    and low not in _WISH_ACRONYMS
                    and not any(ch in "aeiouy" for ch in low)
                )
                or re.search(r"[bcdfghjklmnpqrstvwxz]{6,}", low)
            ):
                raise ValueError(
                    f"{field_label} must contain proper English words, "
                    f"not '{word}'."
                )
        normalized_items.append(text)
    return normalized_items


def validate_value(
    field,
    value,
    profile_mode=False,
    allow_empty_location=False,
    clamp_legacy_limits=False,
):
    """Validate the exact agreed field type, returning normalized values."""
    if field not in PREFERENCE_FIELDS:
        raise ValueError(f"Unsupported preference field: {field}.")
    if value is None:
        return None
    if field in NUMBER_LIMITS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} must be a number.")
        if not math.isfinite(value):
            raise ValueError(f"{field} must be a finite number.")
        if profile_mode:
            minimum, maximum = PROFILE_NUMBER_LIMITS[field]
            if clamp_legacy_limits:
                legacy_min = NUMBER_LIMITS[field][0]
                if value < legacy_min:
                    raise ValueError(
                        f"{field} must be between {minimum:g} and {maximum:g}."
                    )
                return round(max(minimum, min(maximum, float(value))), 2)
            if not minimum <= value <= maximum:
                raise ValueError(
                    f"{field} must be between {minimum:g} and {maximum:g}."
                )
            return round(float(value), 2)
        minimum, maximum = NUMBER_LIMITS[field]
        if not minimum <= value <= maximum:
            raise ValueError(
                f"{field} must be between {minimum} and {maximum}."
            )
        return round(value, 2)
    if field == "location":
        locs = normalize_list(
            value, required=not allow_empty_location, allow_coordinates=True
        )
        for loc in locs:
            validate_location_syntax(loc, label="Default location")
        return locs
    if field == "dietary_requirements":
        return normalize_list(value, DIETARY_CHOICES)
    if field == OTHER_PREFERENCES:
        return normalize_list(value, allow_ratings=True)
    if field in CUISINE_FIELDS:
        label = (
            "Default preferred cuisines"
            if field == "liked_cuisines"
            else "Default disliked cuisines"
        )
        return validate_cuisine_list(value, field_label=label)
    return clean_text(value, 1000, allow_empty=True)


def validate_search_distance(value, mode=None):
    """Validate a search-only maximum distance in kilometres for a mode."""
    limits = SEARCH_MODE_LIMITS.get(mode) if mode else None
    low, high = limits["max_distance_km"] if limits else (0.01, 50.0)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError(
            f"max_distance_km must be between {low:g} and {high:g}."
        )
    return round(float(value), 2)


def validate_travel_minutes(value, mode=None):
    """Validate a search-only maximum journey time in minutes."""
    limits = SEARCH_MODE_LIMITS.get(mode) if mode else None
    low, high = (
        limits["max_travel_minutes"] if limits else TRANSIT_MINUTES_RANGE
    )
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError(
            f"Travel time must be between {low:g} and {high:g} minutes."
        )
    return round(value, 2)


def validate_updates(updates, profile_mode=False, allow_empty_location=False):
    """Reject obsolete keys even if null; null updates never erase answers."""
    if not isinstance(updates, dict):
        raise ValueError("Preference updates must be a dictionary.")
    normalized = {}
    for field, value in updates.items():
        value = validate_value(
            field,
            value,
            profile_mode=profile_mode,
            allow_empty_location=allow_empty_location,
        )
        if value is not None:
            normalized[field] = value
    return normalized


def validate_preferences(preferences, clamp_legacy_limits=False):
    """Validate a full persisted preference record without adding fields."""
    if not isinstance(preferences, dict) or set(preferences) != set(
        PREFERENCE_FIELDS
    ):
        raise ValueError(
            "Saved profile does not match the current BIS schema."
        )
    result = {
        key: validate_value(
            key,
            value,
            profile_mode=True,
            allow_empty_location=True,
            clamp_legacy_limits=clamp_legacy_limits,
        )
        for key, value in preferences.items()
    }
    overlap = set(result["liked_cuisines"] or []) & set(
        result["disliked_cuisines"] or []
    )
    if overlap:
        joined = ", ".join(sorted(overlap))
        raise ValueError(
            f"Resolve cuisines listed as both liked and disliked: {joined}."
        )
    return result


def validate_user(user, clamp_legacy_limits=False):
    """Require the exact account and preference schema."""
    if not isinstance(user, dict) or set(user) != USER_FIELDS:
        raise ValueError(
            "Saved account does not match the current BIS schema."
        )
    if not isinstance(user["userID"], str) or not user["userID"]:
        raise ValueError("Invalid userID.")
    if type(user["email_verified"]) is not bool:
        raise ValueError("email_verified must be a boolean.")
    return {
        "userID": user["userID"],
        "email": normalize_email(user["email"]),
        "email_verified": user["email_verified"],
        "username": (
            normalize_username(user["username"])
            if user["username"] is not None
            else None
        ),
        "preferences": validate_preferences(
            user["preferences"], clamp_legacy_limits=clamp_legacy_limits
        ),
    }


# Recognition-only unsupported cuisine names.
UNSUPPORTED_CUISINES = {
    "spanish",
    "greek",
    "brazilian",
    "ethiopian",
    "german",
    "british",
    "pakistani",
    "bangladeshi",
    "nepalese",
    "sri lankan",
    "cambodian",
    "laotian",
    "burmese",
    "taiwanese",
    "singaporean",
}

RECOGNIZED_CUISINES = frozenset(
    {
        *CUISINES,
        *UNSUPPORTED_CUISINES,
        "portuguese",
        "swiss",
        "austrian",
        "belgian",
        "dutch",
        "irish",
        "scottish",
        "polish",
        "russian",
        "ukrainian",
        "georgian",
        "armenian",
        "hungarian",
        "czech",
        "swedish",
        "norwegian",
        "danish",
        "finnish",
        "scandinavian",
        "nordic",
        "moroccan",
        "tunisian",
        "egyptian",
        "nigerian",
        "south african",
        "african",
        "persian",
        "iranian",
        "iraqi",
        "syrian",
        "jordanian",
        "yemeni",
        "israeli",
        "arab",
        "arabic",
        "afghan",
        "uzbek",
        "tibetan",
        "mongolian",
        "hong kong",
        "macanese",
        "cantonese",
        "sichuan",
        "szechuan",
        "hunan",
        "shanghainese",
        "beijing",
        "teochew",
        "hokkien",
        "hakka",
        "hainanese",
        "fujian",
        "dongbei",
        "xinjiang",
        "uyghur",
        "okinawan",
        "kyushu",
        "hokkaido",
        "north indian",
        "south indian",
        "punjabi",
        "gujarati",
        "kerala",
        "chettinad",
        "kashmiri",
        "bengali",
        "goan",
        "hyderabadi",
        "mughlai",
        "javanese",
        "padang",
        "sundanese",
        "balinese",
        "nonya",
        "nyonya",
        "eurasian",
        "malaysian",
        "asian",
        "southeast asian",
        "east asian",
        "south asian",
        "european",
        "latin",
        "latin american",
        "south american",
        "caribbean",
        "jamaican",
        "cuban",
        "peruvian",
        "argentinian",
        "argentine",
        "colombian",
        "chilean",
        "australian",
        "aussie",
        "new zealand",
        "kiwi",
        "canadian",
        "hawaiian",
        "cajun",
        "creole",
        "tex mex",
        "tex-mex",
        "southern",
        "soul food",
        "seafood",
        "fast food",
        "hawker",
        "zi char",
        "tze char",
        "kopitiam",
        "mamak",
        "local",
        "ramen",
        "sushi",
        "sashimi",
        "izakaya",
        "udon",
        "soba",
        "tonkatsu",
        "katsu",
        "tempura",
        "yakitori",
        "teppanyaki",
        "yakiniku",
        "donburi",
        "omakase",
        "matcha",
        "dim sum",
        "yum cha",
        "hotpot",
        "hot pot",
        "steamboat",
        "mala",
        "mala xiang guo",
        "bbq",
        "kbbq",
        "korean bbq",
        "charcoal bbq",
        "mookata",
        "lok lok",
        "satay",
        "laksa",
        "chicken rice",
        "bak kut teh",
        "nasi lemak",
        "nasi padang",
        "briyani",
        "biryani",
        "prata",
        "roti prata",
        "murtabak",
        "thosai",
        "dosai",
        "dosa",
        "tandoori",
        "naan",
        "curry",
        "banh mi",
        "pho",
        "pad thai",
        "tom yum",
        "som tam",
        "pizza",
        "pasta",
        "burger",
        "burgers",
        "steak",
        "steakhouse",
        "grill",
        "wings",
        "fried chicken",
        "sandwich",
        "sandwiches",
        "wraps",
        "salad",
        "salads",
        "poke",
        "acai",
        "tapas",
        "paella",
        "risotto",
        "gelato",
        "ice cream",
        "bakery",
        "cafe",
        "cafes",
        "coffee",
        "brunch",
        "breakfast",
        "dessert",
        "desserts",
        "pastry",
        "pastries",
        "cake",
        "cakes",
        "boba",
        "bubble tea",
        "noodle",
        "noodles",
        "wanton mee",
        "bak chor mee",
        "char kway teow",
        "hokkien mee",
        "roast meat",
        "duck",
        "roast duck",
        "porridge",
        "congee",
        "soup",
        "dumpling",
        "dumplings",
        "gyoza",
        "rice bowl",
        "bento",
        "tacos",
        "burrito",
        "burritos",
        "quesadilla",
        "kebab",
        "kebabs",
        "shawarma",
        "falafel",
        "hummus",
        "gyros",
        "vegan",
        "vegetarian",
        "plant based",
        "plant-based",
        "healthy",
        "organic",
        "buffet",
        "fine dining",
        "bistro",
        "bar",
        "pub",
        "gastropub",
        "supper",
        "street food",
        "comfort food",
        "home style",
        "homestyle",
    }
)


def normalize_cuisine_token(item):
    """Normalize whitespace, casing, and trailing 'cuisine' suffix."""
    text = " ".join(str(item or "").strip().lower().split())
    if not text:
        return ""
    stripped = _CUISINE_SUFFIX_RX.sub("", text).strip()
    return stripped or text


def is_recognized_cuisine(item):
    """Return True if the normalized cuisine matches the curated catalog."""
    return normalize_cuisine_token(item) in RECOGNIZED_CUISINES


def validate_cuisine_list(value, field_label="Cuisine"):
    """Validate cuisine entries syntactically, rejecting gibberish/slang."""
    if not isinstance(value, list):
        raise ValueError("Expected a list of text entries.")
    result = []
    for raw in value:
        cleaned = clean_text(raw, 40)
        token = normalize_cuisine_token(cleaned)
        if not token or token in {"none", "any", "any cuisine", "all"}:
            raise ValueError(
                f"{field_label}: enter a real cuisine or leave it blank "
                "(e.g. Japanese, Spanish, Seafood)."
            )
        if token == "halal":
            raise ValueError(
                f"{field_label}: Halal is a dietary requirement — use the "
                "MUIS Halal option instead."
            )
        if not _CUISINE_TEXT_RX.fullmatch(token):
            raise ValueError(
                f"{field_label}: '{cleaned}' is not a valid cuisine name "
                "(letters only, e.g. Japanese, Spanish, Dim Sum)."
            )
        words = re.findall(r"[a-z]+", token)
        if (
            not words
            or len(words) > 4
            or sum(len(w) for w in words) < 3
        ):
            raise ValueError(
                f"{field_label}: '{cleaned}' is not a valid cuisine name "
                "(e.g. Japanese, Spanish, Seafood)."
            )
        if token in _INVALID_CUISINE_WORDS or (
            token not in RECOGNIZED_CUISINES
            and any(w in _INVALID_CUISINE_WORDS for w in words)
        ):
            raise ValueError(
                f"{field_label}: '{cleaned}' is not a valid cuisine name "
                "(e.g. Japanese, Spanish, Seafood)."
            )
        if token not in RECOGNIZED_CUISINES:
            for word in words:
                if (
                    re.search(r"(.)\1\1", word)
                    or any(seq in word for seq in _WISH_KEYBOARD_MASH)
                    or (
                        len(word) >= 3
                        and word not in _CUISINE_ACRONYMS
                        and not any(ch in "aeiouy" for ch in word)
                    )
                    or re.search(r"[bcdfghjklmnpqrstvwxz]{6,}", word)
                ):
                    raise ValueError(
                        f"{field_label}: '{cleaned}' is not a valid "
                        "cuisine name (e.g. Japanese, Spanish, Seafood)."
                    )
        if token not in result:
            result.append(token)
    return result
