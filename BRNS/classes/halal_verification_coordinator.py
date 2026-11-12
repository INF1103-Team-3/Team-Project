"""Coordinate BRNS halal evidence with the external BRC boundary."""


class HalalVerificationCoordinator:
    """Apply BRC evidence without owning ranking or persistence."""

    def __init__(self, logic_manager, io_manager, verifier, logger):
        self._logic = logic_manager
        self._io = io_manager
        self._verifier = verifier
        self._log = logger

    @staticmethod
    def brc_restaurant(candidate):
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

    def verify(self, candidates, request, recommendations):
        if "halal" not in request["dietary_requirements"]:
            return candidates, None
        order = self._logic.recommendation_order(candidates, recommendations)
        database_missing = self._verifier.database_missing()
        summary = {
            "candidates": len(order), "checked": 0, "verified": 0,
            "not_verified": 0, "errors": 0, "error_type": None,
            "database_missing": database_missing, "google_fallback": 0,
            "excluded": 0,
        }
        checked_candidates = []
        for original in candidates:
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
            checked_candidates.append(candidate)
        self._io.show_halal_verification_start(
            len(order), database_missing)
        supports_batch = (
            self._verifier.supports_batch()
            if hasattr(self._verifier, "supports_batch")
            else hasattr(self._verifier, "verify_batch")
        )
        if supports_batch and order:
            self._verify_batch(candidates, checked_candidates, order, summary)
        else:
            self._verify_individually(
                candidates, checked_candidates, order, summary)
        summary["google_fallback"] = sum(
            candidate.get("halal_certification") == "unofficial"
            for candidate in checked_candidates
        )
        summary["excluded"] = (
            summary["candidates"] - summary["verified"]
            - summary["google_fallback"]
        )
        self._io.show_halal_verification_summary(summary)
        return checked_candidates, summary

    def _verify_individually(self, candidates, checked_candidates, order, summary):
        for index in order:
            candidate = checked_candidates[index]
            try:
                checked = self._verifier.verify(
                    self.brc_restaurant(candidates[index]))
            except Exception as error:
                self._record_verify_error(index, error, summary)
                continue
            self._apply_checked(candidate, index, checked, summary)

    def _verify_batch(self, candidates, checked_candidates, order, summary):
        payload = [self.brc_restaurant(candidates[index]) for index in order]
        try:
            checked_rows = self._verifier.verify_batch(payload)
        except Exception as error:
            self._log.debug_log(
                "BRC batch check failed, falling back to per-candidate checks: "
                f"{type(error).__name__}: {self._log.safe_error_detail(error)}",
                "WARNING",
                "BRNS.main.verify_halal_candidates",
            )
            self._verify_individually(
                candidates, checked_candidates, order, summary)
            return
        for index, checked in zip(order, checked_rows):
            self._apply_checked(checked_candidates[index], index, checked, summary)

    def _record_verify_error(self, index, error, summary):
        detail = self._log.safe_error_detail(error)
        self._log.debug_log(
            f"BRC check failed for candidate {index}: "
            f"{type(error).__name__}: {detail}", "ERROR",
            "BRNS.main.verify_halal_candidates",
        )
        summary["errors"] += 1
        if summary["error_type"] is None:
            summary["error_type"] = type(error).__name__

    def _apply_checked(self, candidate, index, checked, summary):
        summary["checked"] += 1
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
            summary["verified"] += 1
            dietary.append("halal")
            cuisines = checked.get("cuisines")
            if isinstance(cuisines, list):
                candidate["cuisines"] = cuisines
        else:
            summary["not_verified"] += 1
            if candidate["halal_hint"]:
                dietary.append("halal")
        candidate["dietary_requirements"] = list(dict.fromkeys(dietary))
        self._log.debug_log(
            f"BRC {'verified' if verified else 'did not verify'} "
            f"candidate {index}.",
            "INFO" if verified else "WARNING",
            "BRNS.main.verify_halal_candidates",
        )
