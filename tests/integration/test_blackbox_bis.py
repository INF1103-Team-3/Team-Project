"""BIS process-level black box tests.

Run with: python -m unittest tests.test_blackbox_bis -v
"""

import json
if __package__:
    from .blackbox_support import BlackBoxFixture, run_blackbox_suite
else:
    from blackbox_support import BlackBoxFixture, run_blackbox_suite


class BISBlackBoxTests(BlackBoxFixture):
    def test_bis_signup_rejects_bad_email_without_saving_it(self):
        """Signup rejects an invalid email.

        Input: Enter a bad email, then sign up with a valid one.
        Expected: Only the valid account is saved; no AI or Maps call occurs.
        Expected output: "Enter a valid email address." then "Signed up."
        """
        self.env["AI_BYPASS"] = "true"
        output = self.run_cli("BIS", [
            "1", "invalid-email", "1", "new@example.com", "New User", "/quit"])
        self.assert_shows(output, "Enter a valid email address.", "Signed up.")
        accounts = json.loads((self.root / "BIS/data/users.json").read_text())
        self.assertEqual([user["email"] for user in accounts.values()],
                         ["new@example.com"])
        self.assertEqual(self.fixture.paths(), [])

    def test_bis_profile_setup_retries_invalid_budget(self):
        """Profile setup retries an invalid budget.

        Input: Enter text for the budget, then correct it to SGD 10.
        Expected: The corrected profile is saved and search can be cancelled.
        Expected output: "Preferences saved." and "Search cancelled."
        """
        self.env["AI_BYPASS"] = "true"
        output = self.run_cli("BIS", [
            "1", "new@example.com", "New User", "Tampines", "yes", "2 km",
            "abc", "10", "none", "none", "none", "none", "/cancel",
            "/quit"])
        self.assert_shows(output, "What is your budget per person?",
                          "Preferences saved.", "Profile complete.",
                          "Search cancelled")
        accounts = json.loads((self.root / "BIS/data/users.json").read_text())
        self.assertEqual(len(accounts), 1)
        profile = next(iter(accounts.values()))["preferences"]
        self.assertEqual(profile["location"], ["tampines"])
        self.assertEqual(profile["budget_per_person"], 10)
        self.assertEqual(profile["max_distance_km"], 2)
        self.assertEqual(self.history(), [])

    def test_bis_bare_travel_number_gets_unit_and_space_separated_cuisines(self):
        """Profile setup understands a travel unit and two cuisines.

        Input: Enter 20 without a unit and type western italian.
        Expected: BIS asks for minutes or km, then saves both cuisines.
        Expected output: "What unit did you mean for 20?" and "Profile complete."
        """
        self.env["AI_BYPASS"] = "true"
        output = self.run_cli("BIS", [
            "1", "new@example.com", "New User", "Tampines", "yes", "20", "2",
            "10", "none", "western italian", "none", "", "/cancel",
            "/quit"])
        self.assert_shows(output, "What unit did you mean for 20?",
                          "Choose 1 for km or 2 for minutes",
                          "Profile complete.", "Search cancelled")
        accounts = json.loads((self.root / "BIS/data/users.json").read_text())
        profile = next(iter(accounts.values()))["preferences"]
        self.assertEqual(profile["max_travel_time_minutes"], 20)
        self.assertEqual(profile["max_distance_km"], 1)
        self.assertEqual(profile["liked_cuisines"], ["western", "italian"])
        self.assertEqual(profile["other_preferences"], [])

    def test_bis_written_travel_number_requires_explicit_unit_choice(self):
        """A written travel number still needs a unit choice.

        Input: Enter ten, choose minutes, and confirm the AI suggestion.
        Expected: The profile saves 10 minutes and its distance equivalent.
        Expected output: "What unit did you mean for 10?" and a confirmation prompt.
        """
        user = self.seed_complete_user()
        user["preferences"]["max_distance_km"] = None
        user["preferences"]["max_travel_time_minutes"] = None
        (self.root / "BIS/data/users.json").write_text(json.dumps({
            user["userID"]: user}))
        output = self.run_cli("BIS", [
            "2", "tester@example.com", "ten", "2", "yes", "/quit"])
        self.assert_shows(output, "How far are you willing to travel?",
                          "What unit did you mean for 10?",
                          "Use 10 mins for your travel preference?")
        accounts = json.loads((self.root / "BIS/data/users.json").read_text())
        profile = accounts[user["userID"]]["preferences"]
        self.assertEqual(profile["max_travel_time_minutes"], 10)
        self.assertEqual(profile["max_distance_km"], 0.5)
        self.assertEqual(self.fixture.paths(), ["/chat/completions"])

    def test_bis_declined_written_travel_interpretation_is_not_saved(self):
        """Declining an AI travel suggestion saves nothing.

        Input: Enter ten, choose km, then decline the suggestion.
        Expected: Both profile travel limits remain empty.
        Expected output: "No preference update was applied."
        """
        user = self.seed_complete_user()
        user["preferences"]["max_distance_km"] = None
        user["preferences"]["max_travel_time_minutes"] = None
        (self.root / "BIS/data/users.json").write_text(json.dumps({
            user["userID"]: user}))
        output = self.run_cli("BIS", [
            "2", "tester@example.com", "ten", "1", "no", "/quit"])
        self.assert_shows(output, "What unit did you mean for 10?",
                          "No preference update was applied")
        accounts = json.loads((self.root / "BIS/data/users.json").read_text())
        profile = accounts[user["userID"]]["preferences"]
        self.assertIsNone(profile["max_distance_km"])
        self.assertIsNone(profile["max_travel_time_minutes"])

    def test_bis_rejects_ai_unit_conflicting_with_explicit_minutes(self):
        """An AI unit cannot override explicit minutes.

        Input: Enter ten minutes while the fixture AI suggests km.
        Expected: BIS rejects the conflict and saves no travel limit.
        Expected output: "Could not confirm the travel unit".
        """
        user = self.seed_complete_user()
        user["preferences"]["max_distance_km"] = None
        user["preferences"]["max_travel_time_minutes"] = None
        (self.root / "BIS/data/users.json").write_text(json.dumps({
            user["userID"]: user}))
        output = self.run_cli("BIS", [
            "2", "tester@example.com", "ten minutes", "/quit"])
        self.assert_shows(output, "Could not confirm the travel unit")
        accounts = json.loads((self.root / "BIS/data/users.json").read_text())
        profile = accounts[user["userID"]]["preferences"]
        self.assertIsNone(profile["max_distance_km"])
        self.assertIsNone(profile["max_travel_time_minutes"])

    def test_bis_confirms_ai_extracted_space_separated_locations(self):
        """Three space-separated locations need confirmation.

        Input: Enter punggol sengkang nex and confirm the extracted areas.
        Expected: All three areas are saved after AI parsing.
        Expected output: "Add these locations: Punggol, Sengkang, Nex?"
        """
        output = self.run_cli("BIS", [
            "1", "new@example.com", "New User", "punggol sengkang nex",
            "yes", "/quit"])
        self.assert_shows(output, "Add these locations: Punggol, Sengkang, Nex?",
                          "Preferences saved.")
        accounts = json.loads((self.root / "BIS/data/users.json").read_text())
        profile = next(iter(accounts.values()))["preferences"]
        self.assertEqual(profile["location"], ["punggol", "sengkang", "nex"])
        self.assertEqual(self.fixture.paths().count("/chat/completions"), 2)

    def test_bis_declined_location_list_is_not_saved(self):
        """Declining extracted locations leaves the profile unchanged.

        Input: Enter three space-separated areas and reject the AI list.
        Expected: No location is saved.
        Expected output: "No preference update was applied."
        """
        output = self.run_cli("BIS", [
            "1", "new@example.com", "New User", "punggol sengkang nex",
            "no", "/quit"])
        self.assert_shows(output, "Add these locations: Punggol, Sengkang, Nex?",
                          "No preference update was applied")
        accounts = json.loads((self.root / "BIS/data/users.json").read_text())
        profile = next(iter(accounts.values()))["preferences"]
        self.assertIsNone(profile["location"])

    def test_bis_ai_corrects_cuisine_typo_only_after_confirmation(self):
        """Cuisine spelling and extraction need confirmation.

        Input: Enter wesaten italian, accept spelling, then accept cuisines.
        Expected: Western and Italian are saved as liked cuisines.
        Expected output: "Use 'western italian' instead?" then "Profile complete."
        """
        user = self.seed_complete_user()
        user["preferences"]["liked_cuisines"] = None
        user["preferences"]["disliked_cuisines"] = None
        user["preferences"]["other_preferences"] = None
        (self.root / "BIS/data/users.json").write_text(json.dumps({
            user["userID"]: user}))
        (self.root / "BIS/data/profile_state.json").write_text("{}")
        output = self.run_cli("BIS", [
            "2", "tester@example.com", "wesaten italian", "yes", "yes",
            "none", "", "/cancel", "/quit"])
        self.assert_shows(output, "Use 'western italian' instead?",
                          "Save likes as western, italian?", "Profile complete.")
        accounts = json.loads((self.root / "BIS/data/users.json").read_text())
        profile = accounts[user["userID"]]["preferences"]
        self.assertEqual(profile["liked_cuisines"], ["western", "italian"])
        self.assertEqual(profile["other_preferences"], [])
        self.assertEqual(self.fixture.paths().count("/chat/completions"), 2)

    def test_bis_declined_cuisine_correction_does_not_save(self):
        """Declining a cuisine spelling fix saves nothing.

        Input: Enter wesaten italian and reject the correction.
        Expected: Liked cuisines remain unchanged.
        Expected output: "Use 'western italian' instead?" then no update.
        """
        user = self.seed_complete_user()
        user["preferences"]["liked_cuisines"] = None
        (self.root / "BIS/data/users.json").write_text(json.dumps({
            user["userID"]: user}))
        output = self.run_cli("BIS", [
            "2", "tester@example.com", "wesaten italian", "no", "/quit"])
        self.assert_shows(output, "Use 'western italian' instead?",
                          "No preference update was applied")
        accounts = json.loads((self.root / "BIS/data/users.json").read_text())
        self.assertIsNone(accounts[user["userID"]]["preferences"]["liked_cuisines"])
        self.assertEqual(self.fixture.paths(), ["/chat/completions"])

    def test_bis_invalid_search_answers_retry_and_valid_search_is_saved(self):
        """The search form retries invalid answers.

        Input: Enter bad travel mode, distance, and budget, then correct each.
        Expected: BIS saves valid choices and skips BRNS in chatbot test mode.
        Expected output: Retry prompts, "Walk up to 2.0 km", and search skipped.
        """
        self.seed_complete_user()
        self.env["AI_BYPASS"] = "true"
        output = self.run_cli("BIS", [
            "2", "tester@example.com", "/search", "1.352,103.944", "yes",
            "fly", "walk", "9", "1", "0", "2", "none", "0", "10",
            "", "/quit"])
        self.assert_shows(output, "Choose walk, drive, or transit.",
                          "Choose 1 or 2", "max_distance_km must be between",
                          "budget_per_person must be between",
                          "Walk up to 2.0 km", "restaurant search skipped")
        state = json.loads((self.root / "BIS/data/profile_state.json").read_text())
        self.assertTrue(state["search"]["blackbox-user"]["completed"])
        self.assertEqual(self.history(), [])
        self.assertEqual(self.fixture.paths(), [])

    def test_bis_transit_search_accepts_profile_time_with_enter(self):
        """Transit search uses the saved travel time.

        Input: Select transit and press Enter at the journey time prompt.
        Expected: The summary shows 40 minutes from the saved profile.
        Expected output: "[Enter = 40 min from profile]" and "Transit up to 40 min".
        """
        self.seed_complete_user()
        self.env["AI_BYPASS"] = "true"
        output = self.run_cli("BIS", [
            "2", "tester@example.com", "/search", "1.352,103.944", "yes",
            "transit", "", "none", "10", "", "", "/quit"])
        self.assert_shows(output, "[Enter = 40 min from profile]",
                          "Transit up to 40 min", "restaurant search skipped")
        self.assertEqual(self.history(), [])

    def test_bis_drive_search_accepts_profile_time_with_enter(self):
        """Driving search uses the saved travel time.

        Input: Select driving time and press Enter at the time prompt.
        Expected: The summary shows 40 minutes from the saved profile.
        Expected output: "[Enter = 40 min from profile]" and "Drive up to 40 min".
        """
        self.seed_complete_user()
        self.env["AI_BYPASS"] = "true"
        output = self.run_cli("BIS", [
            "2", "tester@example.com", "/search", "1.352,103.944", "yes",
            "drive", "2", "", "", "none", "10", "", "", "/quit"])
        self.assert_shows(output, "[Enter = 40 min from profile]",
                          "Drive up to 40 min", "restaurant search skipped")
        self.assertEqual(self.history(), [])

    def test_bis_ai_interpretation_can_be_declined_before_brns(self):
        """Declining BIS search interpretation stops before BRNS.

        Input: Fill the search form, then reject the AI search summary.
        Expected: Search is cancelled; Places and BRNS are never called.
        Expected output: "Search cancelled." followed by "Goodbye!"
        """
        self.seed_complete_user()
        output = self.run_cli("BIS", [
            "2", "tester@example.com", "/search", "1.352,103.944", "yes",
            "walk", "1", "2", "none", "10", "", "no", "/quit"])
        self.assert_shows(output, "Today's search", "Search with these choices?",
                          "Search cancelled")
        self.assertNotIn("Your profile is saved", output)
        self.assertNotIn("Profile saved. Goodbye!", output)
        self.assertIn("Goodbye!", output)
        self.assertEqual(self.fixture.paths(), ["/chat/completions"])
        self.assertEqual(self.history(), [])



if __name__ == "__main__":
    run_blackbox_suite(BISBlackBoxTests)
