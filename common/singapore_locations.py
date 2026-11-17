"""Shared Singapore location validation, seed directory, and geocode filter."""

import math
import re

SG_LAT_BOUNDS = (1.15, 1.48)
SG_LNG_BOUNDS = (103.60, 104.10)
SG_COUNTRY_CENTER = (1.352083, 103.819836)

COORDINATE_PATTERN = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*$"
)
_POSTAL_ONLY_PATTERN = re.compile(r"^\s*(\d+)\s*$")
_SG_POSTAL_PREFIX_PATTERN = re.compile(
    r"^(?:singapore|sg|s\s*\(?)\s*(\d+)\)?$", re.IGNORECASE
)
_BARE_SINGAPORE_PATTERN = re.compile(
    r"^(?:singapore|s'?pore|sg)$", re.IGNORECASE
)
_REPEAT_LETTER_PATTERN = re.compile(r"(?!iii\b)([a-z])\1\1")

# Omit "erty" because valid words (e.g. Liberty, Property) contain it.
LOCATION_KEYBOARD_MASH = (
    "asdf",
    "sdfg",
    "dfgh",
    "fghj",
    "ghjk",
    "hjkl",
    "jklm",
    "qwer",
    "wert",
    "qwrt",
    "tyui",
    "uiop",
    "zxcv",
    "xcvb",
    "cvbn",
    "vbnm",
    "qazw",
    "wsxc",
    "edcr",
    "rfvt",
)

KNOWN_SG_ABBRS = frozenset(
    {
        "amk",
        "bb",
        "bldg",
        "blk",
        "bm",
        "bp",
        "bt",
        "cbd",
        "cck",
        "chij",
        "ctrl",
        "gl",
        "hdb",
        "imm",
        "jem",
        "jln",
        "lrg",
        "mbs",
        "mrt",
        "nex",
        "np",
        "ntu",
        "nus",
        "nyp",
        "plq",
        "qt",
        "rp",
        "sim",
        "sit",
        "smu",
        "sp",
        "sutd",
        "t1",
        "t2",
        "t3",
        "t4",
        "tg",
        "tp",
        "tpy",
        "yck",
        "iii",
    }
)

NON_LOCATION_SLANG_WORDS = frozenset(
    {
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
        "bruh",
        "yeet",
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
        "cb",
        "ccb",
        "knn",
        "knnb",
        "knnbccb",
        "lampa",
        "lanjiao",
        "cheebai",
        "chibai",
        "kanina",
        "nabei",
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
        "asshole",
        "dick",
        "cock",
        "pussy",
        "cunt",
        "bastard",
        "whore",
        "slut",
        "test",
        "testing",
        "hello",
        "hi",
        "hey",
        "bye",
        "none",
        "nothing",
        "anything",
        "whatever",
        "random",
        "stuff",
        "null",
        "undefined",
        "nan",
        "blorp",
        "foobar",
        "foo",
        "baz",
        "qwerty",
    }
)
STRICT_PROFANITY_LOCATION_WORDS = frozenset(
    {
        "cb",
        "ccb",
        "knn",
        "knnb",
        "knnbccb",
        "lampa",
        "lanjiao",
        "cheebai",
        "chibai",
        "kanina",
        "nabei",
        "pukimak",
        "kontol",
        "babi",
        "anjing",
        "cibai",
        "fuck",
        "fucking",
        "shit",
        "bitch",
        "asshole",
        "dick",
        "cunt",
        "bastard",
        "whore",
        "slut",
    }
)
_ORDINAL_DIGIT_WORD_RX = re.compile(r"^\d+(?:st|nd|rd|th)$")
_MIXED_GIBBERISH_DIGIT_LETTER_RX = re.compile(
    r"^(?:[a-z]+\d{2,}[a-z]+|\d{2,}[a-z]{2,}\d*)$"
)

SG_SEED_LOCATIONS = (
    ("Bugis", "Area / MRT", 1.3008, 103.8557, ("bugis junction", "bugis+")),
    (
        "Orchard",
        "Area / MRT",
        1.3048,
        103.8318,
        ("orchard road", "ion orchard"),
    ),
    ("Somerset", "Area / MRT", 1.3005, 103.8390, ("313@somerset",)),
    ("Dhoby Ghaut", "MRT Interchange", 1.2993, 103.8455, ("plaza singapura",)),
    ("City Hall", "Area / MRT", 1.2932, 103.8520, ("raffles city",)),
    ("Raffles Place", "CBD / MRT", 1.2839, 103.8515, ("cbd",)),
    (
        "Marina Bay",
        "Area / MRT",
        1.2819,
        103.8540,
        ("marina bay sands", "mbs"),
    ),
    ("Clarke Quay", "Riverside / MRT", 1.2886, 103.8466, ("boat quay",)),
    ("Chinatown", "Heritage / MRT", 1.2849, 103.8439, ()),
    ("Tanjong Pagar", "CBD / MRT", 1.2764, 103.8467, ()),
    ("Outram Park", "MRT Interchange", 1.2802, 103.8395, ()),
    ("Tiong Bahru", "Area / MRT", 1.2862, 103.8270, ("tiong bahru plaza",)),
    ("Little India", "Heritage / MRT", 1.3068, 103.8492, ()),
    ("Farrer Park", "Area / MRT", 1.3125, 103.8541, ("city square mall",)),
    (
        "Kampong Glam",
        "Heritage Area",
        1.3025,
        103.8595,
        ("arab street", "haji lane"),
    ),
    ("Lavender", "Area / MRT", 1.3075, 103.8630, ()),
    ("Kallang", "Area / MRT", 1.3115, 103.8714, ("stadium",)),
    (
        "HarbourFront",
        "Area / MRT",
        1.2654,
        103.8220,
        ("vivocity", "vivo city"),
    ),
    (
        "Sentosa",
        "Island / Resort",
        1.2494,
        103.8303,
        ("resorts world sentosa",),
    ),
    ("Novena", "Area / MRT", 1.3204, 103.8438, ("velocity",)),
    ("Newton", "Area / MRT", 1.3123, 103.8380, ("newton circus",)),
    ("Toa Payoh", "Town / MRT", 1.3327, 103.8473, ("tpy",)),
    ("Bishan", "Town / MRT", 1.3512, 103.8485, ("junction 8",)),
    ("Ang Mo Kio", "Town / MRT", 1.3691, 103.8454, ("amk", "amk hub")),
    ("Serangoon", "Town / MRT", 1.3497, 103.8736, ("nex",)),
    ("Kovan", "Area / MRT", 1.3602, 103.8851, ("heartland mall",)),
    ("Hougang", "Town / MRT", 1.3712, 103.8923, ("hougang mall",)),
    ("Sengkang", "Town / MRT", 1.3917, 103.8955, ()),
    (
        "Compass One",
        "Mall (Sengkang)",
        1.3924,
        103.8954,
        ("compass one mall", "545078", "singapore 545078"),
    ),
    ("Rivervale Plaza", "Mall (Sengkang)", 1.3858, 103.9020, ()),
    (
        "Punggol",
        "Town / MRT",
        1.4043,
        103.9025,
        ("waterway point", "828761", "singapore 828761"),
    ),
    ("Potong Pasir", "Area / MRT", 1.3314, 103.8691, ()),
    ("Woodleigh", "Area / MRT", 1.3392, 103.8708, ("woodleigh mall",)),
    (
        "Yishun",
        "Town / MRT",
        1.4295,
        103.8350,
        ("northpoint", "northpoint city"),
    ),
    ("Khatib", "Area / MRT", 1.4173, 103.8330, ()),
    ("Canberra", "Area / MRT", 1.4431, 103.8297, ()),
    ("Sembawang", "Town / MRT", 1.4491, 103.8200, ("sun plaza",)),
    ("Woodlands", "Town / MRT", 1.4369, 103.7865, ("causeway point",)),
    ("Admiralty", "Area / MRT", 1.4406, 103.8009, ()),
    (
        "Paya Lebar",
        "Area / MRT",
        1.3182,
        103.8926,
        ("plq", "paya lebar quarter"),
    ),
    ("Eunos", "Area / MRT", 1.3198, 103.9032, ()),
    ("Bedok", "Town / MRT", 1.3240, 103.9302, ("bedok mall",)),
    (
        "Tampines",
        "Town / MRT",
        1.3541,
        103.9441,
        ("tampines mall", "our tampines hub"),
    ),
    ("Pasir Ris", "Town / MRT", 1.3721, 103.9474, ("white sands",)),
    ("Simei", "Area / MRT", 1.3432, 103.9534, ("eastpoint mall",)),
    ("Tanah Merah", "Area / MRT", 1.3272, 103.9463, ()),
    ("Changi", "East / Airport", 1.3644, 103.9915, ("changi airport",)),
    ("Jewel Changi Airport", "Mall / Landmark", 1.3602, 103.9898, ("jewel",)),
    ("Katong", "Heritage Area", 1.3048, 103.9052, ("joo chiat", "i12 katong")),
    ("Marine Parade", "Area / MRT", 1.3027, 103.9050, ("parkway parade",)),
    (
        "Jurong East",
        "Town / MRT",
        1.3331,
        103.7423,
        ("jem", "westgate", "imm"),
    ),
    ("Jurong West", "Town", 1.3404, 103.7090, ()),
    ("Boon Lay", "Area / MRT", 1.3386, 103.7061, ("jurong point",)),
    ("Pioneer", "Area / MRT", 1.3376, 103.6973, ()),
    ("Clementi", "Town / MRT", 1.3151, 103.7652, ("clementi mall",)),
    (
        "Buona Vista",
        "Area / MRT",
        1.3072,
        103.7900,
        ("star vista", "one-north"),
    ),
    ("Holland Village", "Area / MRT", 1.3119, 103.7962, ()),
    ("Queenstown", "Town / MRT", 1.2942, 103.8061, ()),
    ("Redhill", "Area / MRT", 1.2896, 103.8168, ()),
    ("Bukit Timah", "Area", 1.3294, 103.8021, ("beauty world",)),
    ("Bukit Batok", "Town / MRT", 1.3490, 103.7495, ("west mall",)),
    ("Bukit Panjang", "Town / MRT", 1.3774, 103.7719, ("hillion mall",)),
    ("Choa Chu Kang", "Town / MRT", 1.3853, 103.7443, ("cck", "lot one")),
    (
        "NUS",
        "University",
        1.2966,
        103.7764,
        ("national university of singapore", "kent ridge"),
    ),
    (
        "NTU",
        "University",
        1.3483,
        103.6831,
        ("nanyang technological university",),
    ),
    (
        "SMU",
        "University",
        1.2963,
        103.8502,
        ("singapore management university",),
    ),
    ("SUTD", "University", 1.3413, 103.9638, ()),
    ("Suntec City", "Mall / Convention", 1.2950, 103.8583, ("promenade",)),
)


def is_in_singapore(latitude, longitude):
    """Return True when coordinates are finite and fall inside Singapore."""
    try:
        lat = float(latitude)
        lng = float(longitude)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(lat)
        and math.isfinite(lng)
        and SG_LAT_BOUNDS[0] <= lat <= SG_LAT_BOUNDS[1]
        and SG_LNG_BOUNDS[0] <= lng <= SG_LNG_BOUNDS[1]
    )


def is_generic_singapore_centroid(latitude, longitude):
    """Return True when coordinates match Google's generic Singapore center."""
    try:
        lat = float(latitude)
        lng = float(longitude)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return False
    return (
        abs(lat - SG_COUNTRY_CENTER[0]) <= 0.0005
        and abs(lng - SG_COUNTRY_CENTER[1]) <= 0.0005
    )


def extract_postal_digits(text):
    """Return digits for bare or 'Singapore ...' postal inputs."""
    clean = re.sub(r"\s+", " ", str(text or "").strip()).strip(".,;")
    m = _POSTAL_ONLY_PATTERN.fullmatch(clean)
    if m:
        return m.group(1)
    m = _SG_POSTAL_PREFIX_PATTERN.fullmatch(clean)
    if m:
        return m.group(1)
    return None


def _validate_sg_postal_digits(digits, label="Location"):
    if len(digits) != 6:
        raise ValueError(
            f"{label} postal code must be 6 Singapore digits (e.g. 545078)."
        )
    sector = int(digits[:2])
    if sector < 1 or sector > 83:
        raise ValueError(
            f"{label} '{digits}' is not a valid Singapore postal code "
            "(e.g. 545078)."
        )


def validate_location_syntax(raw, label="Location"):
    """Validate that raw text looks like a real Singapore location query."""
    clean = re.sub(r"\s+", " ", str(raw or "").strip())
    if not clean:
        raise ValueError(f"{label} cannot be empty.")
    if any(ord(ch) < 32 for ch in str(raw or "")):
        raise ValueError(f"{label} contains invalid characters.")
    if len(clean) > 160:
        raise ValueError(f"{label} is too long (maximum 160 characters).")

    coord_match = COORDINATE_PATTERN.fullmatch(clean)
    if coord_match:
        lat, lng = map(float, coord_match.groups())
        if not is_in_singapore(lat, lng):
            raise ValueError("Enter coordinates within Singapore.")
        return clean

    postal_digits = extract_postal_digits(clean)
    if postal_digits is not None:
        _validate_sg_postal_digits(postal_digits, label=label)
        return clean

    if _BARE_SINGAPORE_PATTERN.fullmatch(clean.strip(".,;!? ")):
        raise ValueError(
            f"{label} 'Singapore' is too broad. Please enter a specific "
            "Singapore area, MRT, landmark, or 6-digit postal code "
            "(e.g. Bugis, Compass One, 545078)."
        )

    if any(ch in clean for ch in ("?", "!", "<", ">", "{", "}", ";")):
        raise ValueError(
            "Please enter a valid Singapore location, area, MRT, or "
            f"6-digit postal code for {label.lower()}."
        )

    lowered = clean.lower()
    if any(seq in lowered for seq in LOCATION_KEYBOARD_MASH):
        raise ValueError(
            f"'{clean}' does not look like a real Singapore location "
            "(e.g. Bugis, Compass One, 545078)."
        )

    if _REPEAT_LETTER_PATTERN.search(lowered):
        raise ValueError(
            f"'{clean}' does not look like a real Singapore location "
            "(e.g. Bugis, Compass One, 545078)."
        )

    alpha_count = sum(1 for ch in lowered if "a" <= ch <= "z")
    digit_count = sum(1 for ch in lowered if "0" <= ch <= "9")
    tokens = [tok for tok in re.findall(r"[a-z0-9]+", lowered) if tok]
    if not tokens or (alpha_count + digit_count) < 3:
        if lowered not in KNOWN_SG_ABBRS:
            raise ValueError(
                "Please enter a specific Singapore location, MRT station, "
                "or 6-digit postal code (e.g. Bugis, Compass One, 545078)."
            )

    for token in tokens:
        if token in STRICT_PROFANITY_LOCATION_WORDS:
            raise ValueError(
                f"'{clean}' does not look like a real Singapore location "
                "(e.g. Bugis, Compass One, 545078)."
            )
        if (
            not token.startswith("blk")
            and not _ORDINAL_DIGIT_WORD_RX.fullmatch(token)
            and _MIXED_GIBBERISH_DIGIT_LETTER_RX.fullmatch(token)
        ):
            raise ValueError(
                f"'{clean}' does not look like a real Singapore location "
                "(e.g. Bugis, Compass One, 545078)."
            )
        letters = "".join(ch for ch in token if "a" <= ch <= "z")
        if not letters:
            continue
        if letters in KNOWN_SG_ABBRS:
            continue
        vowels = sum(1 for ch in letters if ch in "aeiouy")
        if len(letters) >= 4 and vowels == 0:
            raise ValueError(
                f"'{clean}' does not look like a real Singapore location "
                "(e.g. Bugis, Compass One, 545078)."
            )
        if len(letters) >= 6 and (vowels / len(letters)) < 0.18:
            raise ValueError(
                f"'{clean}' does not look like a real Singapore location "
                "(e.g. Bugis, Compass One, 545078)."
            )

    content_tokens = [
        tok for tok in tokens if tok not in {"singapore", "sg"}
    ] or tokens
    if (
        len(content_tokens) <= 2
        and all(tok in NON_LOCATION_SLANG_WORDS for tok in content_tokens)
    ):
        raise ValueError(
            f"'{clean}' does not look like a real Singapore location "
            "(e.g. Bugis, Compass One, 545078)."
        )

    return clean


def lookup_seed_singapore_location(query):
    """Return (label, lat, lng) when query matches a known Singapore hub."""
    key = re.sub(r"\s+", " ", str(query or "").strip()).lower()
    if not key:
        return None
    stripped = re.sub(r"\bmrt(?:\s+station)?\b", "", key).strip()
    for label, _category, lat, lng, aliases in SG_SEED_LOCATIONS:
        candidates = (label.lower(), *(alias.lower() for alias in aliases))
        if key in candidates or (stripped and stripped in candidates):
            return label, float(lat), float(lng)
    return None


def suggest_seed_locations(query, limit=6):
    """Return prefix/substring ranked suggestions from SG_SEED_LOCATIONS."""
    clean = re.sub(r"\s+", " ", str(query or "").strip()).lower()
    if not clean:
        return [
            {
                "label": label,
                "secondary": f"{category} · Singapore",
                "source": "seed",
            }
            for label, category, _lat, _lng, _aliases in SG_SEED_LOCATIONS[
                :limit
            ]
        ]

    prefix_matches = []
    contains_matches = []
    seen = set()
    for label, category, _lat, _lng, aliases in SG_SEED_LOCATIONS:
        norm_label = label.lower()
        if norm_label in seen:
            continue
        terms = [norm_label, *(a.lower() for a in aliases)]
        if any(term.startswith(clean) for term in terms):
            seen.add(norm_label)
            prefix_matches.append(
                {
                    "label": label,
                    "secondary": f"{category} · Singapore",
                    "source": "seed",
                }
            )
        elif any(clean in term for term in terms):
            seen.add(norm_label)
            contains_matches.append(
                {
                    "label": label,
                    "secondary": f"{category} · Singapore",
                    "source": "seed",
                }
            )
    return (prefix_matches + contains_matches)[:limit]


_GEO_PRECISION_TYPES = frozenset(
    {
        "street_address",
        "route",
        "intersection",
        "premise",
        "subpremise",
        "neighborhood",
        "sublocality",
        "sublocality_level_1",
        "locality",
        "postal_code",
        "transit_station",
        "subway_station",
        "train_station",
        "bus_station",
        "light_rail_station",
        "shopping_mall",
        "park",
        "university",
        "school",
        "hospital",
        "airport",
        "tourist_attraction",
    }
)
_NOISY_PARTIAL_POI_TYPES = frozenset(
    {"bar", "night_club", "liquor_store", "casino"}
)


def is_acceptable_singapore_geocode(result, query=""):
    """Return True if a geocode result resolves specifically in Singapore."""
    if not isinstance(result, dict):
        return False
    point = (result.get("geometry") or {}).get("location") or {}
    if not is_in_singapore(point.get("lat"), point.get("lng")):
        return False

    types = {
        str(t).strip().lower()
        for t in (result.get("types") or [])
        if str(t).strip()
    }
    formatted = str(result.get("formatted_address") or "").strip().lower()

    if "country" in types:
        return False
    if formatted in ("singapore", "singapore, singapore"):
        return False
    if types and types <= {
        "political",
        "locality",
        "colloquial_area",
        "administrative_area_level_1",
    }:
        if not formatted or formatted.startswith("singapore"):
            return False

    if is_generic_singapore_centroid(point.get("lat"), point.get("lng")):
        specific = {"street_address", "route", "postal_code", "premise"}
        if not (types & specific):
            return False

    if result.get("partial_match") and not (types & _GEO_PRECISION_TYPES):
        q_tokens = [
            tok
            for tok in re.findall(r"[a-z0-9]+", str(query or "").lower())
            if tok not in {"singapore", "sg"}
        ]
        comp_texts = " ".join(
            str(comp.get(field) or "").lower()
            for comp in (result.get("address_components") or [])
            if isinstance(comp, dict)
            for field in ("long_name", "short_name")
        )
        addr_blob = f"{formatted} {comp_texts}"
        has_token_in_address = bool(q_tokens) and any(
            len(tok) >= 3 and tok in addr_blob for tok in q_tokens
        )
        if not has_token_in_address and (
            (types & _NOISY_PARTIAL_POI_TYPES)
            or (
                len(q_tokens) == 1
                and len(q_tokens[0]) <= 4
                and q_tokens[0] not in KNOWN_SG_ABBRS
            )
        ):
            return False

    postal_digits = extract_postal_digits(query)
    if postal_digits and (
        types or formatted or result.get("address_components")
    ):
        comp_postals = {
            str(comp.get(field) or "").strip()
            for comp in (result.get("address_components") or [])
            if isinstance(comp, dict)
            and "postal_code" in (comp.get("types") or [])
            for field in ("long_name", "short_name")
        }
        has_exact_postal = postal_digits in comp_postals or (
            postal_digits in formatted
        )
        if not has_exact_postal:
            return False

    return True
