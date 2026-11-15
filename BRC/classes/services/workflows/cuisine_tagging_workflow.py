"""Cuisine-tagging job coordinating AI, domain policy, and cache checkpoints."""

from BRC.classes.ai.errors.ai_response_error import AIResponseError
from BRC.classes.ai.errors.ai_service_error import AIServiceError


class CuisineTaggingWorkflow:
    """Preserve pending order, checkpoint timing, and partial-failure behavior."""

    def __init__(self, report):
        self._report = report

    def run(self, listings, cache, ai, logic, save_cache=None):
        """Return cuisine tags for every listing in the original order."""
        tags, pending = logic.prepare_cuisine_tags(listings, cache)
        if len(pending) < len(listings):
            self._report(
                f"AI: reused or derived {len(listings) - len(pending)} "
                f"cached cuisine tags; {len(pending)} still need AI.")
        if save_cache:
            save_cache(cache)
        size = ai.batch_size()
        for start in range(0, len(pending), size):
            batch = pending[start:start + size]
            self._report(
                "AI: tagging cuisines for restaurants "
                f"{start + 1}–{start + len(batch)} of {len(pending)} "
                f"(currently {batch[0][1].name or 'unknown'})")
            try:
                answers = ai.tag_batch(batch)
            except AIResponseError as error:
                self._report(
                    "AI: skipped this batch after invalid responses "
                    f"({error}); it will be retried on the next build.")
                continue
            except AIServiceError as error:
                self._report(
                    f"AI: Gemini is unavailable ({error}); "
                    f"{len(pending) - start} restaurants were left untagged "
                    "and will be retried next build.")
                break
            for index, cuisines in answers.items():
                tags[index] = cuisines
                cache.put(listings[index], cuisines)
            if save_cache:
                save_cache(cache)
        return tags
