"""Security behavior at the email verification boundary."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))

import io_manager  # noqa: E402
from support import config as app_config  # noqa: E402
from support.email_verification import (  # noqa: E402
    challenge, email_delivery, service,
)
from tests.friendly_test_report import run_friendly_suite  # noqa: E402

DEFAULT_RESET_SECONDS = 600
TEST_CONFIG = {"verification_attempt_reset_seconds": DEFAULT_RESET_SECONDS}


class EmailVerificationTests(unittest.TestCase):
    report_group = "Email verification"

    def setUp(self):
        self.function_calls = []
        self.observed_results = []

    def note_call(self, name):
        self.function_calls.append(name)

    def note_result(self, result):
        self.observed_results.append(result)

    def report_details(self):
        return {
            "target_label": "Code under test",
            "target": "BIS email verification, delivery, config, and IO",
            "observed_label": "Observed result",
            "observed": self.observed_results,
            "calls_label": "Function calls",
            "calls": self.function_calls,
            "no_calls": "No function call was reached; see failure details.",
        }

    def test_maps_email_contains_selected_restaurant_and_link(self):
        """A Maps link email includes the selected restaurant.

        Input: Restaurant name and Google Maps URL for a sample recipient.
        Expected: The email has the correct recipient, name, link, and type.
        Expected output: A composed Maps email; SMTP delivery is mocked.
        """
        config = {
            "smtp_host": "smtp.example.com", "smtp_security": "ssl",
            "smtp_port": 465, "smtp_username": "", "smtp_password": "",
            "smtp_from_email": "sender@example.com",
        }
        with patch.object(email_delivery, "_send_message") as send:
            self.note_call("email_delivery.send_maps_link_email")
            email_delivery.send_maps_link_email(
                "guest@example.com", "Second Cafe",
                "https://www.google.com/maps/dir/?api=1", config)
        self.note_call("email_delivery._send_message (mocked)")
        message, passed_config, kind = send.call_args.args
        self.assertEqual(passed_config, config)
        self.assertEqual(kind, "Maps link email")
        self.assertEqual(message["To"], "guest@example.com")
        self.assertIn("Second Cafe", message.get_content())
        self.assertIn("https://www.google.com/maps/dir/?api=1",
                      message.get_content())
        self.note_result("Maps email contains Second Cafe and its directions link.")
        self.note_result("No real SMTP connection was made.")

    def test_legacy_challenge_remains_usable(self):
        """An older challenge without a window timestamp still works.

        Input: A valid code and legacy challenge missing attempt_window_started_at.
        Expected: Verification succeeds and restores the original window start.
        Expected output: No error; attempt window starts at timestamp 1000.
        """
        self.note_call("challenge.new_challenge")
        code, current = challenge.new_challenge(
            now=1000, attempt_reset_seconds=DEFAULT_RESET_SECONDS)
        legacy = dict(current)
        legacy.pop("attempt_window_started_at")
        self.note_call("challenge.check_challenge")
        updated, error = challenge.check_challenge(
            legacy, code, now=1001,
            attempt_reset_seconds=DEFAULT_RESET_SECONDS)
        self.assertIsNone(error)
        self.assertEqual(updated["attempt_window_started_at"], 1000)
        self.note_result("Verification accepted; legacy attempt window restored.")

    def test_resend_cannot_reset_failed_attempt_limit(self):
        """Resending a code cannot erase failed attempts.

        Input: Four wrong codes, resend, one more wrong code, then wait for reset.
        Expected: The fifth failure locks the challenge until the reset window.
        Expected output: "Too many incorrect attempts" before reset; 0 after.
        """
        self.note_call("challenge.new_challenge")
        _, current = challenge.new_challenge(
            now=1000, attempt_reset_seconds=DEFAULT_RESET_SECONDS)
        self.note_call("challenge.check_challenge (four wrong attempts)")
        for _ in range(4):
            current, error = challenge.check_challenge(
                current, "not a code", now=1001,
                attempt_reset_seconds=DEFAULT_RESET_SECONDS)
            self.assertEqual(error, "Incorrect verification code.")
        self.note_call("challenge.new_challenge (resend)")
        _, resent = challenge.new_challenge(
            current, now=1060, attempt_reset_seconds=DEFAULT_RESET_SECONDS)
        self.assertEqual(resent["attempts"], 4)
        self.note_call("challenge.check_challenge (fifth wrong attempt)")
        locked, error = challenge.check_challenge(
            resent, "not a code", now=1061,
            attempt_reset_seconds=DEFAULT_RESET_SECONDS)
        self.assertIn("Too many incorrect attempts", error)
        self.note_call("challenge.new_challenge (blocked resend)")
        with self.assertRaisesRegex(ValueError, "Too many incorrect"):
            challenge.new_challenge(
                locked, now=1120,
                attempt_reset_seconds=DEFAULT_RESET_SECONDS)
        self.note_call("challenge.new_challenge (after reset)")
        _, renewed = challenge.new_challenge(
            locked, now=1601, attempt_reset_seconds=DEFAULT_RESET_SECONDS)
        self.assertEqual(renewed["attempts"], 0)
        self.note_result("Resend kept four failed attempts; the fifth caused a lockout.")
        self.note_result("After the reset window, the attempt count returned to 0.")

    def test_one_minute_attempt_reset_preserves_code_expiry(self):
        """A one-minute attempt reset does not change code expiry.

        Input: Exhaust attempts; check at 59 seconds and again at 60 seconds.
        Expected: The lockout resets at 60 seconds while code expiry stays fixed.
        Expected output: Lockout at 59 seconds; valid code succeeds at 60.
        """
        self.note_call("challenge.new_challenge")
        code, current = challenge.new_challenge(
            now=1000, attempt_reset_seconds=60)
        self.note_call("challenge.check_challenge (failed attempts)")
        for _ in range(challenge.VERIFICATION_MAX_ATTEMPTS):
            current, _ = challenge.check_challenge(
                current, "wrong", now=1001, attempt_reset_seconds=60)
        self.note_call("challenge.check_challenge (before reset)")
        _, blocked = challenge.check_challenge(
            current, code, now=1059, attempt_reset_seconds=60)
        self.assertIn("Too many incorrect attempts", blocked)
        self.note_call("challenge.check_challenge (at reset)")
        updated, error = challenge.check_challenge(
            current, code, now=1060, attempt_reset_seconds=60)
        self.assertIsNone(error)
        self.assertEqual(updated["attempts"], 0)
        self.assertEqual(updated["expires_at"], 1600)
        self.note_result("Lockout remained at 59 seconds and cleared at 60.")
        self.note_result("Code expiry stayed at timestamp 1600.")

    def test_attempt_reset_minutes_loads_from_environment(self):
        """The attempt reset interval loads from the environment.

        Input: VERIFICATION_ATTEMPT_RESET_MINUTES=1.
        Expected: Configuration converts one minute to 60 seconds.
        Expected output: verification_attempt_reset_seconds = 60.
        """
        with patch.dict(os.environ, {
                "VERIFICATION_ATTEMPT_RESET_MINUTES": "1"}):
            self.note_call("config.load_config")
            self.assertEqual(
                app_config.load_config()["verification_attempt_reset_seconds"],
                60,
            )
        self.note_result("Reset interval loaded as 60 seconds.")

    def test_verified_account_must_enter_code_to_resume(self):
        """A verified account still enters a code when resuming.

        Input: A previously verified account and a mocked six-digit code.
        Expected: BIS requests a code and verifies it before returning the user.
        Expected output: Verified user returned only after code confirmation.
        """
        user = {"userID": "example", "email_verified": True}
        with (
            patch.object(io_manager.email_service, "get_challenge",
                         return_value=None),
            patch.object(io_manager.email_service, "request_code") as send,
            patch.object(io_manager.email_service, "verify_code",
                         return_value=user) as verify,
            patch.object(io_manager, "read_input", return_value="123456"),
            patch.object(io_manager, "display_message"),
        ):
            self.note_call("io_manager.verify_email_interactively")
            self.assertIs(io_manager.verify_email_interactively(
                user, {"smtp_bypass": False}), user)
        send.assert_called_once_with(user, {"smtp_bypass": False})
        verify.assert_called_once_with(user, "123456", {"smtp_bypass": False})
        self.note_call("email_service.request_code (mocked)")
        self.note_call("email_service.verify_code (mocked)")
        self.note_result("User returned after the code request and verification.")

    def test_successful_resume_consumes_code_without_rewriting_account(self):
        """Successful resume consumes the code without rewriting the account.

        Input: A valid pending challenge for an existing verified user.
        Expected: Verification state is cleared; the account record is untouched.
        Expected output: Existing user returned; pending challenge removed.
        """
        user = {"userID": "example", "email_verified": True}
        self.note_call("challenge.new_challenge")
        code, pending = challenge.new_challenge(
            attempt_reset_seconds=DEFAULT_RESET_SECONDS)
        with (
            patch.object(service.data_manager, "get_state",
                         return_value=pending),
            patch.object(service.data_manager, "set_state") as set_state,
            patch.object(service.data_manager, "save") as save,
        ):
            self.note_call("email_service.verify_code")
            self.assertIs(service.verify_code(user, code, TEST_CONFIG), user)
        set_state.assert_called_once_with("verification", "example", None)
        save.assert_not_called()
        self.note_call("data_manager.set_state (mocked)")
        self.note_result("Pending challenge cleared; account save was not called.")

    def test_smtp_failure_keeps_existing_challenge(self):
        """An SMTP failure preserves the existing verification challenge.

        Input: Request a new code while the mocked mail sender raises an error.
        Expected: The error reaches the caller and challenge state is not saved.
        Expected output: "SMTP failed" exception; no state write.
        """
        user = {"userID": "example", "email": "test@example.com"}
        self.note_call("challenge.new_challenge")
        _, previous = challenge.new_challenge(
            now=1000, attempt_reset_seconds=DEFAULT_RESET_SECONDS)
        with (
            patch.object(service, "get_challenge", return_value=previous),
            patch.object(service.challenge, "new_challenge",
                         return_value=("123456", previous)),
            patch.object(service.email_delivery, "send_verification_email",
                         side_effect=RuntimeError("SMTP failed")),
            patch.object(service.data_manager, "set_state") as save,
        ):
            self.note_call("email_service.request_code")
            with self.assertRaisesRegex(RuntimeError, "SMTP failed"):
                service.request_code(user, TEST_CONFIG)
        save.assert_not_called()
        self.note_call("email_delivery.send_verification_email (mocked failure)")
        self.note_result("SMTP failure raised; the existing challenge was retained.")
        self.note_result("Verification state was not overwritten.")


if __name__ == "__main__":
    run_friendly_suite(
        unittest.defaultTestLoader.loadTestsFromTestCase(EmailVerificationTests),
        "BiteFinder email verification tests")
