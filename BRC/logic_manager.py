"""Verify exact MUIS outlet evidence before changing certification status."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def muis_brand_key(name: str) -> str:
    """Strip a Google branch suffix before querying a MUIS brand."""
    base = re.split(r"\s*(?:\(|@|\|)\s*", name or "", maxsplit=1)[0]
    return " ".join(re.findall(r"[a-z0-9]+", base.casefold()))


def muis_postal(record: dict) -> str | None:
    postal = str(record.get("postal_code") or "")
    if re.fullmatch(r"\d{6}", postal):
        return postal
    matches = re.findall(r"\b\d{6}\b", str(record.get("address") or ""))
    return matches[-1] if matches else None


_MUIS_UNIT = re.compile(
    r"(?:#\s*|\b)((?:B\d{1,2}|\d{2})[-/]\d{2,3}(?:/\d{2,3})?[A-Z]?)\b",
    re.IGNORECASE,
)


def _muis_unit(address: str) -> str | None:
    match = _MUIS_UNIT.search(address)
    return re.sub(r"[^A-Z0-9]", "", match.group(1).upper()) if match else None


def _muis_address_key(address: str) -> str:
    text = _MUIS_UNIT.sub(" ", address)
    text = re.sub(r"\b(?:singapore|\d{6})\b", " ", text, flags=re.IGNORECASE)
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _same_muis_outlet(restaurant: dict, listing: dict, listings: list[dict]) -> bool:
    """Use original MUIS facts to guard against same-brand branch mistakes."""
    if (listing.get("scheme") != "Eating Establishment"
            or muis_postal(restaurant) != listing.get("postal_code")):
        return False
    if listing.get("status") not in (None, "listed", "active"):
        return False
    expiry = listing.get("valid_until")
    if expiry is not None:
        from datetime import date, datetime, timedelta, timezone
        try:
            expiry_date = date.fromisoformat(expiry)
        except (TypeError, ValueError):
            return False
        if expiry_date < datetime.now(timezone(timedelta(hours=8))).date():
            return False
    name = muis_brand_key(restaurant["name"])
    listed_name = muis_brand_key(listing["name"])
    if not name or not listed_name or SequenceMatcher(
            None, name, listed_name).ratio() < 0.78:
        return False
    address = restaurant["address"]
    listed_address = listing["address"]
    if SequenceMatcher(None, _muis_address_key(address),
                       _muis_address_key(listed_address)).ratio() < 0.65:
        return False
    unit, listed_unit = _muis_unit(address), _muis_unit(listed_address)
    if bool(unit) != bool(listed_unit) or (unit and unit != listed_unit):
        return False
    if not unit:
        same_brand_at_postal = [entry for entry in listings
                                if entry.get("postal_code") == listing["postal_code"]
                                and muis_brand_key(entry.get("name", "")) == listed_name]
        if len(same_brand_at_postal) != 1:
            return False
    return True


def check_muis_records(records: list[dict], snapshot: dict,
                       proposals: list[str | None]) -> list[dict]:
    """Apply only evidence-backed certification changes to full records."""
    from datetime import datetime, timezone

    if len(records) != len(proposals):
        raise ValueError("BRC AI did not return one proposal per restaurant.")
    coverage = set(snapshot["covered_names"])
    for record in records:
        if muis_brand_key(record["name"]) not in coverage:
            raise ValueError(
                f"MUIS snapshot does not cover {record['name']!r}. "
                "Refresh it with this restaurant before checking.")
    listings = snapshot["listings"]
    by_number = {item["certificate_number"]: item for item in listings}
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    checked = []
    for record, proposal in zip(records, proposals):
        output = dict(record)
        listing = by_number.get(proposal) if proposal else None
        verified = bool(listing and _same_muis_outlet(record, listing, listings))
        previous = record.get("muis_check")
        if verified:
            dietary = list(record.get("dietary") or [])
            added_halal = "halal" not in dietary
            if added_halal:
                dietary.append("halal")
            output["dietary"] = dietary
            prior = (previous.get("prior_certification", "none")
                     if isinstance(previous, dict)
                     and record.get("halal_certification") == "official"
                     else record.get("halal_certification", "none"))
            output["halal_certification"] = "official"
            output["muis_check"] = {
                "status": "verified", "checked_at": checked_at,
                "source_url": snapshot["source_url"],
                "snapshot_fetched_at": snapshot["fetched_at"],
                "certificate_number": listing["certificate_number"],
                "listing_id": listing.get("listing_id"),
                "listing_name": listing["name"],
                "listing_address": listing["address"],
                "valid_until": listing.get("valid_until"),
                "prior_certification": prior,
                "added_halal": (added_halal or bool(
                    isinstance(previous, dict) and previous.get("added_halal"))),
            }
        else:
            if record.get("halal_certification") == "official":
                prior = (previous.get("prior_certification", "none")
                         if isinstance(previous, dict) else "none")
                output["halal_certification"] = (
                    prior if prior in ("unofficial", "none") else "none")
                if not isinstance(previous, dict) or previous.get("added_halal"):
                    output["dietary"] = [item for item in
                                         (record.get("dietary") or [])
                                         if item != "halal"]
            output["muis_check"] = {
                "status": "not_verified", "checked_at": checked_at,
                "source_url": snapshot["source_url"],
                "snapshot_fetched_at": snapshot["fetched_at"],
            }
        checked.append(output)
    return checked
