"""Result model for an independently verified restaurant."""


class CheckedRestaurant:
    """Shape one BRC result from a record and optional verified outlet."""

    def __init__(self, record, outlet, checked_at):
        self._record = record
        self._outlet = outlet
        self._checked_at = checked_at

    def to_dict(self):
        result = self._record.to_dict()
        if self._outlet is None:
            if result.get("halal_certification") == "official":
                result["halal_certification"] = "none"
                result["dietary"] = [
                    item for item in result.get("dietary", [])
                    if item != "halal"]
            result["muis_check"] = {
                "status": "not_verified",
                "checked_at": self._checked_at,
            }
            return result
        certificate = self._outlet.certificate
        result["dietary"] = list(dict.fromkeys([
            *(result.get("dietary") or []), "halal"]))
        result["halal_certification"] = "official"
        result["cuisines"] = self._outlet.cuisines
        if not result.get("cuisine") and self._outlet.cuisines:
            result["cuisine"] = self._outlet.cuisines[0]
        result["muis_check"] = {
            "status": "verified",
            "checked_at": self._checked_at,
            "certificate_number": certificate.number,
            "listing_id": certificate.listing_id,
            "source_url": certificate.source_url,
            "valid_until": certificate.valid_until,
        }
        return result
