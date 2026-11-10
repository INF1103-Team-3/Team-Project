"""Map recommendation results into the existing persisted record formats."""
import re


class RecommendationRecordMapper:
    @staticmethod
    def restaurant_record(candidate):
        place_id = candidate.get("google_place_id")
        if (not isinstance(place_id, str) or not place_id
                or not candidate.get("name")):
            return None
        dietary = {
            item for item in candidate.get("dietary_requirements") or []
            if item in ("halal", "vegetarian")
        }
        if candidate.get("halal_hint"):
            dietary.add("halal")
        address = candidate.get("address")
        postal = candidate.get("postal_code")
        if not postal and isinstance(address, str):
            match = re.search(
                r"\bSingapore\s+(\d{6})\b", address, re.IGNORECASE)
            postal = match.group(1) if match else None
        cuisines = candidate.get("cuisines") or []
        rating = candidate.get("rating")
        reviews = candidate.get("rating_count")
        wheelchair = candidate.get("wheelchair_accessible")
        muis_check = candidate.get("muis_check")
        officially_verified = (
            candidate.get("halal_certification") == "official"
            and isinstance(muis_check, dict)
            and muis_check.get("status") == "verified"
        )
        return {
            "google_place_id": place_id,
            "name": candidate["name"],
            "postal_code": postal,
            "address": address if address != "unavailable" else None,
            "number": candidate.get("number"),
            "g_rating": (
                str(rating) if type(rating) in (int, float) else None),
            "g_no_reviews": str(reviews) if type(reviews) is int else None,
            "cuisine": (
                cuisines[0]
                if cuisines and cuisines[0] != "unknown" else None),
            "dietary": sorted(dietary),
            "avg_price_low_sgd": candidate.get("price_start"),
            "avg_price_high_sgd": candidate.get("price_end"),
            "opening_hours": candidate.get("opening_hours"),
            "wheelchair_accessible": (
                wheelchair if type(wheelchair) is bool else None),
            "halal_certification": (
                "official" if officially_verified
                else "unofficial" if "halal" in dietary else "none"),
        }

    @staticmethod
    def search_summary(request, results, source):
        origin = request["origin"]
        entry = {
            "mode": source,
            "origin": [origin["latitude"], origin["longitude"]],
            "travel_mode": request["mode"],
            "cuisine": request["cuisine"],
        }
        if source == "live-google":
            entry["top_match_place_ids"] = [
                item["restaurant"]["google_place_id"]
                for item in results["matches"]
                if item["restaurant"].get("google_place_id")
            ]
        else:
            entry["top_matches"] = [
                item["restaurant"]["name"] for item in results["matches"]
            ]
        return entry
