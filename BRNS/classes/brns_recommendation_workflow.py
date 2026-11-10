"""The ordered IO to AI to Logic to Data BRNS search workflow."""

import time


class BRNSRecommendationWorkflow:
    """Run one recommendation pipeline through the four manager roles."""

    def __init__(
            self, io_manager, ai_manager, logic_manager, data_manager,
            halal_verifier, config, logger):
        self._io = io_manager
        self._ai = ai_manager
        self._logic = logic_manager
        self._data = data_manager
        self._halal_verifier = halal_verifier
        self._config = config
        self._log = logger

    def search(self, bis_json, previous_restaurants=()):
        trace_token = self._log.start_trace()
        started = time.monotonic()
        self._log.debug_log(
            "Search started.", "INFO", "BRNS.main.search")
        try:
            request = self._io.accept_bis_json(bis_json)
            self._log.debug_log(
                "BIS JSON validated.", "INFO",
                "BRNS.io_manager.accept_bis_json",
            )
            if not self._ai.has_configured_provider():
                raise RuntimeError(
                    "BRNS needs a configured AI provider to complete this "
                    "search."
                )
            if (self._config.USE_LIVE_GOOGLE
                    and not self._config.GOOGLE_MAPS_API_KEY):
                raise RuntimeError(
                    "Set GOOGLE_MAPS_API_KEY for live restaurant search.")
            candidates = self._io.find_candidates(request)
            self._log.debug_log(
                f"Gathered {len(candidates)} candidates.", "INFO",
                "BRNS.io_manager.find_candidates",
            )
            if not candidates:
                raise RuntimeError(
                    "No restaurants found, or restaurant search is "
                    "unavailable."
                )
            self._io.show_ai_ranking_start(
                len(candidates), self._config.AI_CHAIN_TIMEOUT_SECONDS)
            recommendations = (
                self._ai.recommend_candidates(
                    request, candidates,
                    previous_restaurants=previous_restaurants,
                )
                if previous_restaurants
                else self._ai.recommend_candidates(request, candidates)
            )
            if recommendations is None:
                raise RuntimeError(
                    "BRNS AI could not recommend restaurants. Please retry.")
            self._log.debug_log(
                f"AI ordered {len(recommendations)} candidate IDs.",
                "INFO", "BRNS.ai_manager.recommend_candidates",
            )
            candidates, halal_verification = self._halal_verifier.verify(
                candidates, request, recommendations)
            results = (
                self._logic.rank_restaurants(
                    candidates, request, recommendations,
                    previous_restaurants=previous_restaurants,
                )
                if previous_restaurants
                else self._logic.rank_restaurants(
                    candidates, request, recommendations)
            )
            self._log.debug_log(
                f"Validated {len(results['matches'])} matches, "
                f"{len(results['alternatives'])} alternatives, "
                f"{results['hidden']} hidden.", "INFO",
                "BRNS.logic_manager.rank_restaurants",
            )
            if halal_verification is not None:
                results["halal_verification"] = halal_verification
            source = (
                "live-google" if self._config.USE_LIVE_GOOGLE
                else "offline-restaurants"
            )
            stored_count = self._data.save_restaurants(candidates)
            self._log.debug_log(
                f"Saved {stored_count} restaurant records."
                if stored_count is not None
                else "Restaurant records could not be saved.",
                "INFO" if stored_count is not None else "WARNING",
                "BRNS.data_manager.save_restaurants",
            )
            saved = self._data.save_search_results(
                request, results, source)
            self._log.debug_log(
                "Search summary saved."
                if saved else "Search summary could not be saved.",
                "INFO" if saved else "WARNING",
                "BRNS.data_manager.save_search_results",
            )
            return results
        except (ValueError, RuntimeError, OSError) as error:
            self._log.debug_log(
                f"Search stopped: {type(error).__name__}.", "ERROR",
                "BRNS.main.search",
            )
            raise
        finally:
            self._log.debug_log(
                f"Search flow finished in "
                f"{time.monotonic() - started:.2f}s.",
                "INFO", "BRNS.main.search",
            )
            self._log.end_trace(trace_token)
