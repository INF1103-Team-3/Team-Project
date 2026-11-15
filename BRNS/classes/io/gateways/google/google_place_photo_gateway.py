"""Google Places (New) photo lookup and thumbnail media download gateway."""

import re
from urllib.parse import quote

import requests

MAX_PHOTO_BYTES = 4 * 1024 * 1024
DEFAULT_PLACES_BASE_URL = "https://places.googleapis.com/v1"
PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


class GooglePlacePhotoGateway:
    """Resolve and download thumbnail bytes for one Google place_id."""

    def __init__(self, config, logger, error_logger):
        self._config = config
        self._log = logger
        self._error_logger = error_logger

    @staticmethod
    def validate_place_id(place_id):
        """Return a sanitized place_id or raise ValueError on invalid characters."""
        clean = str(place_id or "").strip()
        if not PLACE_ID_RE.fullmatch(clean):
            raise ValueError("Invalid place identifier.")
        return clean

    def _base_url(self):
        return (
            getattr(self._config, "PLACES_DETAILS_BASE_URL", DEFAULT_PLACES_BASE_URL)
            or DEFAULT_PLACES_BASE_URL
        ).rstrip("/")

    @staticmethod
    def _clean_content_type(raw):
        return str(raw or "").split(";", 1)[0].strip().lower()

    @staticmethod
    def _extract_attribution(photo_meta):
        attributions = photo_meta.get("authorAttributions")
        if not isinstance(attributions, list) or not attributions:
            return ""
        first = attributions[0]
        if not isinstance(first, dict):
            return ""
        return str(first.get("displayName") or "").strip()[:120]

    def _resolve_photo_metadata(self, place_id, api_key):
        url = f"{self._base_url()}/places/{quote(place_id, safe='')}"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "photos",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code in (400, 404):
                return "not_found", "", ""
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as err:
            self._error_logger("place_photo_details", err)
            return "error", "", ""

        photos = payload.get("photos") if isinstance(payload, dict) else None
        if not isinstance(photos, list):
            return "not_found", "", ""
        for item in photos:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip().lstrip("/")
            if name.startswith("places/") and "/photos/" in name:
                return "ok", name, self._extract_attribution(item)
        return "not_found", "", ""

    def _download_media(self, photo_name, api_key, max_width_px):
        media_url = f"{self._base_url()}/{quote(photo_name, safe='/')}/media"
        headers = {"X-Goog-Api-Key": api_key}
        params = {"maxWidthPx": int(max_width_px), "skipHttpRedirect": "true"}
        try:
            media_resp = requests.get(
                media_url, headers=headers, params=params, timeout=15
            )
            media_resp.raise_for_status()
            direct_ct = self._clean_content_type(
                media_resp.headers.get("Content-Type")
            )
            if direct_ct.startswith("image/"):
                img_bytes = bytes(media_resp.content or b"")
                content_type = direct_ct
            else:
                photo_uri = str((media_resp.json() or {}).get("photoUri") or "").strip()
                if not photo_uri.startswith(("https://", "http://")):
                    return None
                img_resp = requests.get(photo_uri, timeout=15)
                img_resp.raise_for_status()
                content_type = self._clean_content_type(
                    img_resp.headers.get("Content-Type")
                )
                img_bytes = bytes(img_resp.content or b"")
        except (requests.RequestException, ValueError, TypeError) as err:
            self._error_logger("place_photo_media", err)
            return None

        if (
            not content_type.startswith("image/")
            or not img_bytes
            or len(img_bytes) > MAX_PHOTO_BYTES
        ):
            return None
        return img_bytes, content_type

    def fetch_photo(self, place_id, max_width_px=480):
        """Fetch photo bytes + metadata from Google Places, or status marker."""
        clean_id = self.validate_place_id(place_id)
        if not getattr(self._config, "USE_LIVE_GOOGLE", True):
            return None
        api_key = str(getattr(self._config, "GOOGLE_MAPS_API_KEY", "") or "").strip()
        if not api_key:
            return None

        status, photo_name, attribution = self._resolve_photo_metadata(
            clean_id, api_key
        )
        if status == "not_found":
            return {"status": "not_found"}
        if status != "ok":
            return None

        downloaded = self._download_media(photo_name, api_key, max_width_px)
        if downloaded is None:
            return None
        img_bytes, content_type = downloaded
        self._log.debug_log(
            f"Fetched place photo ({len(img_bytes)} bytes).",
            "INFO",
            "BRNS.place_photo.fetch",
        )
        return {
            "status": "ok",
            "data": img_bytes,
            "content_type": content_type,
            "photo_name": photo_name,
            "author_attribution": attribution,
        }
