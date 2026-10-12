"""BIS to BRNS process-level black box tests.

Run with: python -m unittest tests.test_blackbox_bis_to_brns -v
"""

import json
if __package__:
    from .blackbox_support import BlackBoxFixture, PLACE_NAMES, run_blackbox_suite
else:
    from blackbox_support import BlackBoxFixture, PLACE_NAMES, run_blackbox_suite


class BISToBRNSBlackBoxTests(BlackBoxFixture):
    def test_bis_to_brns_retries_input_and_shows_route(self):
        """A BIS search reaches BRNS and displays a route.

        Input: Retry bad location and mode, then request a driving route.
        Expected: Geocode, Places, matrix, ranking AI, and route calls complete.
        Expected output: "Found 1 match and 1 alternative" and driving directions.
        """
        self.seed_complete_user()
        output = self.run_cli("BIS", [
            "2", "tester@example.com", "/search", "0,0", "530912", "yes",
            "fly", "drive", "2", "20", "2", "none", "10", "", "yes",
            "1", "1", "", "/quit"])
        self.assert_shows(output, "Enter coordinates within Singapore.",
                          "Found: 530912", "Choose walk, drive, or transit.",
                          "Drive up to 20 min (live traffic)",
                          "Found 1 match and 1 alternative", PLACE_NAMES[0],
                          "Drive route to Near Cafe", "Head north")
        paths = self.fixture.paths()
        self.assertEqual(paths.count("/geocode"), 1, paths)
        self.assertEqual(paths.count("/nearby"), 1, paths)
        self.assertEqual(paths.count("/matrix"), 1, paths)
        self.assertEqual(paths.count("/route"), 1, paths)
        self.assertGreaterEqual(paths.count("/chat/completions"), 2, paths)
        prompts = [body["messages"][0]["content"] for body in
                   self.fixture.bodies("/chat/completions")]
        self.assertTrue(any("Interpret today's restaurant wish" in prompt
                            for prompt in prompts), prompts)
        self.assertTrue(any("Rank every supplied restaurant candidate" in prompt
                            for prompt in prompts), prompts)
        for body in self.fixture.bodies("/matrix") + self.fixture.bodies("/route"):
            self.assertEqual(body.get("routingPreference"), "TRAFFIC_AWARE")
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.history()[0]["top_match_place_ids"], ["test-place-1"])
        cache = json.loads((self.root / "data/geocode_cache.json").read_text())
        self.assertEqual(cache["530912"], [1.352, 103.944])

    def test_enter_starts_search_and_repeat_uses_same_choices_with_new_top_match(self):
        """Repeating a search can find a different top restaurant.

        Input: Press Enter to start, then choose repeat with the same choices.
        Expected: BIS calls BRNS twice and the second ranking has a new top match.
        Expected output: "Top match: Near Cafe." then "Top match: Sixth Cafe."
        """
        self.seed_complete_user()
        self.fixture.six_matches = True
        output = self.run_cli("BIS", [
            "2", "tester@example.com", "/search", "1.352,103.944", "yes",
            "walk", "1", "2", "none", "10", "", "", "6", "", "/quit"])
        self.assert_shows(output, "Search with these choices?",
                          "Found 5 matches", "Top match: Near Cafe.",
                          "Top match: Sixth Cafe.")
        self.assertEqual(output.count("Searching restaurants..."), 2)
        self.assertEqual(self.fixture.paths().count("/nearby"), 2)
        self.assertEqual(self.fixture.paths().count("/matrix"), 2)
        self.assertEqual(len(self.history()), 2)
        self.assertEqual([entry["top_match_place_ids"][0] for entry in self.history()],
                         ["test-place-1", "test-place-6"])
        ai_calls = self.fixture.bodies("/chat/completions")
        recommendation_calls = [body for body in ai_calls if
            "Rank every supplied restaurant candidate" in
            body["messages"][0]["content"]]
        self.assertEqual(len(recommendation_calls), 2)
        previous = json.loads(
            recommendation_calls[1]["messages"][1]["content"])
        self.assertEqual(len(previous["previous_restaurants"]), 5)
        self.assertEqual(previous["previous_restaurants"][0], "Near Cafe")

    def test_repeat_explains_when_no_new_restaurants_are_available(self):
        """A repeated search explains when results are exhausted.

        Input: Search, then repeat without changing the choices.
        Expected: BIS says no new restaurants are available after the second call.
        Expected output: "No new restaurants found for these choices".
        """
        self.seed_complete_user()
        output = self.run_cli("BIS", [
            "2", "tester@example.com", "/search", "1.352,103.944", "yes",
            "walk", "1", "2", "none", "10", "", "", "6", "", "/quit"])
        self.assert_shows(output, "No new restaurants found for these choices")
        self.assertEqual(output.count("Searching restaurants..."), 2)
        self.assertEqual(len(self.history()), 2)


if __name__ == "__main__":
    run_blackbox_suite(BISToBRNSBlackBoxTests)
