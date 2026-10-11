"""BRNS process-level black box tests.

Run with: python -m unittest tests.test_blackbox_brns -v
"""

import json
if __package__:
    from .blackbox_support import (BlackBoxFixture, PLACE_NAMES,
                                   run_blackbox_suite, search_request)
else:
    from blackbox_support import (BlackBoxFixture, PLACE_NAMES,
                                  run_blackbox_suite, search_request)


class BRNSBlackBoxTests(BlackBoxFixture):
    def test_brns_valid_json_shows_match_and_alternative(self):
        """BRNS ranks restaurants from valid search JSON.

        Input: Send a valid BIS request directly to BRNS/main.py.
        Expected: Places, route matrix, and ranking AI yield a match and alternative.
        Expected output: "Matches (1)" and "Alternatives (1)".
        """
        output = self.run_cli("BRNS", json.dumps(search_request()))
        self.assert_shows(output, "Matches (1)", "Alternatives (1)",
                          PLACE_NAMES[0], PLACE_NAMES[1])
        self.assertEqual(self.fixture.paths(),
                         ["/nearby", "/matrix", "/chat/completions"])
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.history()[0]["top_matches"], [PLACE_NAMES[0]])

    def test_brns_invalid_json_never_calls_places_or_saves_history(self):
        """BRNS rejects invalid search JSON at its input boundary.

        Input: Try malformed JSON, missing fields, bad values, and invalid modes.
        Expected: Each input is rejected before HTTP calls or history writes.
        Expected output: A specific validation error for each invalid payload.
        """
        invalid = [
            ("{bad", "valid BIS search JSON"),
            (json.dumps({key: value for key, value in search_request().items()
                         if key != "traffic_aware"}), "ten BIS search fields"),
            (json.dumps(dict(search_request(), unexpected=True)),
             "ten BIS search fields"),
            (json.dumps(search_request(origin=dict(
                search_request()["origin"], latitude=50))), "within Singapore"),
            (json.dumps(search_request(max_travel_minutes=20)),
             "exactly one travel limit"),
            (json.dumps(search_request(budget_per_person=-1)),
             "budget_per_person must be between"),
            (json.dumps(search_request(dietary_requirements="halal")),
             "must be lists"),
            (json.dumps(search_request(mode="walk", max_distance_km=None,
                                       max_travel_minutes=20,
                                       traffic_aware=True)), "Live traffic"),
        ]
        for payload, expected in invalid:
            with self.subTest(expected=expected, payload=payload[:50]):
                output = self.run_cli("BRNS", payload)
                self.assert_shows(output, expected)
                self.assertEqual(self.fixture.paths(), [])
                self.assertEqual(self.history(), [])

    def test_brns_driving_traffic_changes_matrix_request(self):
        """Driving traffic changes the route matrix request.

        Input: Search once without traffic and once with live traffic.
        Expected: Only the second matrix call uses TRAFFIC_AWARE routing.
        Expected output: Driving results showing "min by drive" both times.
        """
        for traffic in (False, True):
            with self.subTest(traffic_aware=traffic):
                self.fixture.calls.clear()
                request = search_request(mode="drive", max_distance_km=None,
                                         max_travel_minutes=20,
                                         traffic_aware=traffic)
                output = self.run_cli("BRNS", json.dumps(request))
                self.assert_shows(output, "min by drive")
                matrix = self.fixture.bodies("/matrix")
                self.assertEqual(len(matrix), 1)
                self.assertEqual(matrix[0].get("routingPreference"),
                                 "TRAFFIC_AWARE" if traffic else None)

    def test_brns_transit_time_uses_verified_minutes(self):
        """Transit search uses transit routes and verified minutes.

        Input: Search with a 20-minute transit journey limit.
        Expected: The matrix uses TRANSIT and the result shows 10 minutes.
        Expected output: "Matches (1)" and "10 min by transit".
        """
        request = search_request(mode="transit", max_distance_km=None,
                                 max_travel_minutes=20)
        output = self.run_cli("BRNS", json.dumps(request))
        self.assert_shows(output, "Matches (1)", "Alternatives (1)",
                          "10 min by transit")
        matrix = self.fixture.bodies("/matrix")
        self.assertEqual(len(matrix), 1)
        self.assertEqual(matrix[0]["travelMode"], "TRANSIT")
        self.assertNotIn("routingPreference", matrix[0])

    def test_brns_invalid_ai_reply_does_not_save_search(self):
        """An invalid AI ranking does not save search history.

        Input: Return a malformed ranking after the Places lookup.
        Expected: BRNS explains the failure and leaves history empty.
        Expected output: "BRNS AI could not recommend restaurants".
        """
        self.fixture.invalid_brns_ai = True
        output = self.run_cli("BRNS", json.dumps(search_request()))
        self.assert_shows(output, "BRNS AI could not recommend restaurants")
        self.assertEqual(self.history(), [])
        self.assertEqual(self.fixture.paths().count("/nearby"), 1)



if __name__ == "__main__":
    run_blackbox_suite(BRNSBlackBoxTests)
