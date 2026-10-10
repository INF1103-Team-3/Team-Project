"""Security behavior at the email verification boundary."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))

import io_manager  # noqa: E402
from support.email_verification import challenge, service  # noqa: E402


class EmailVerificationTests(unittest.TestCase):
    def test_legacy_challenge_remains_usable(self):
        code, current = challenge.new_challenge(now=1000)
        legacy = dict(current)
        legacy.pop("attempt_window_started_at")
        updated, error = challenge.check_challenge(legacy, code, now=1001)
        self.assertIsNone(error)
        self.assertEqual(updated["attempt_window_started_at"], 1000)

    def test_resend_cannot_reset_failed_attempt_limit(self):
        _, current = challenge.new_challenge(now=1000)
        for _ in range(4):
            current, error = challenge.check_challenge(
                current, "not a code", now=1001)
            self.assertEqual(error, "Incorrect verification code.")
        _, resent = challenge.new_challenge(current, now=1060)
        self.assertEqual(resent["attempts"], 4)
        locked, error = challenge.check_challenge(
            resent, "not a code", now=1061)
        self.assertIn("Too many incorrect attempts", error)
        with self.assertRaisesRegex(ValueError, "Too many incorrect"):
            challenge.new_challenge(locked, now=1120)
        _, renewed = challenge.new_challenge(locked, now=1601)
        self.assertEqual(renewed["attempts"], 0)

    def test_verified_account_must_enter_code_to_resume(self):
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
            self.assertIs(io_manager.verify_email_interactively(
                user, {"smtp_bypass": False}), user)
        send.assert_called_once_with(user, {"smtp_bypass": False})
        verify.assert_called_once_with(user, "123456")

    def test_successful_resume_consumes_code_without_rewriting_account(self):
        user = {"userID": "example", "email_verified": True}
        code, pending = challenge.new_challenge()
        with (
            patch.object(service.data_manager, "get_state",
                         return_value=pending),
            patch.object(service.data_manager, "set_state") as set_state,
            patch.object(service.data_manager, "save") as save,
        ):
            self.assertIs(service.verify_code(user, code), user)
        set_state.assert_called_once_with("verification", "example", None)
        save.assert_not_called()

    def test_smtp_failure_keeps_existing_challenge(self):
        user = {"userID": "example", "email": "test@example.com"}
        _, previous = challenge.new_challenge(now=1000)
        with (
            patch.object(service, "get_challenge", return_value=previous),
            patch.object(service.challenge, "new_challenge",
                         return_value=("123456", previous)),
            patch.object(service.email_delivery, "send_verification_email",
                         side_effect=RuntimeError("SMTP failed")),
            patch.object(service.data_manager, "set_state") as save,
        ):
            with self.assertRaises(RuntimeError):
                service.request_code(user, {})
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
