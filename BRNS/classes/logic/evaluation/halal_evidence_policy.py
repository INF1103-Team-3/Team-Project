"""Business rules for applying independent BRC evidence to BRNS candidates."""


class HalalEvidencePolicy:
    """Keep official certification distinct from unverified Google hints."""

    @staticmethod
    def brc_record(candidate):
        record = dict(candidate)
        dietary = [
            item for item in candidate.get("dietary_requirements") or []
            if item in ("halal", "vegetarian")
        ]
        record["dietary"] = dietary
        record["halal_certification"] = (
            "unofficial"
            if candidate.get("halal_hint") or "halal" in dietary
            else "none"
        )
        return record


    @staticmethod
    def initial_candidate(original):
        candidate = dict(original)
        google_halal = (
            original.get("halal_hint") is True
            or "halal" in (
                original.get("dietary_requirements") or []))
        candidate["muis_check"] = {"status": "not_verified"}
        candidate["halal_certification"] = (
            "unofficial" if google_halal else "none")
        candidate["halal_hint"] = google_halal
        candidate["dietary_requirements"] = [
            item
            for item in candidate.get("dietary_requirements") or []
            if item != "halal"
        ]
        if google_halal:
            candidate["dietary_requirements"].append("halal")
        return candidate

    @staticmethod
    def apply(candidate, checked):
        muis_check = checked.get("muis_check")
        verified = (
            checked.get("halal_certification") == "official"
            and isinstance(muis_check, dict)
            and muis_check.get("status") == "verified"
        )
        candidate["muis_check"] = (
            muis_check if isinstance(muis_check, dict)
            else {"status": "not_verified"}
        )
        candidate["halal_certification"] = (
            "official" if verified
            else candidate["halal_certification"]
        )
        candidate["halal_hint"] = (
            False if verified else candidate["halal_hint"])
        dietary = [
            item
            for item in candidate.get("dietary_requirements") or []
            if item != "halal"
        ]
        if verified:
            dietary.append("halal")
            cuisines = checked.get("cuisines")
            if isinstance(cuisines, list):
                candidate["cuisines"] = cuisines
        else:
            if candidate["halal_hint"]:
                dietary.append("halal")
        candidate["dietary_requirements"] = list(dict.fromkeys(dietary))
        return verified
