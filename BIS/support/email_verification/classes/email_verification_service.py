"""Account verification orchestration across independent collaborators."""


class EmailVerificationService:
    """Coordinate challenge rules, delivery, and BIS account persistence."""

    def __init__(self, data_manager, challenge_manager, email_delivery):
        self._data_manager = data_manager
        self._challenge_manager = challenge_manager
        self._email_delivery = email_delivery

    def get_challenge(self, user_id):
        saved = self._data_manager.get_state("verification", user_id)
        return (
            self._challenge_manager.validate(saved)
            if saved else None
        )

    def request_code(self, user, config):
        """Send a code and save state only after successful delivery."""
        code, pending = self._challenge_manager.create(
            self.get_challenge(user["userID"]),
            attempt_reset_seconds=(
                config["verification_attempt_reset_seconds"]),
        )
        self._email_delivery.send_verification_email(
            user["email"], code, config)
        self._data_manager.set_state(
            "verification", user["userID"], pending)

    def verify_code(self, user, code, config):
        """Persist failed attempts or complete account verification."""
        user_id = user["userID"]
        updated, error = self._challenge_manager.check(
            self.get_challenge(user_id), code,
            attempt_reset_seconds=(
                config["verification_attempt_reset_seconds"]),
        )
        if updated and error:
            self._data_manager.set_state("verification", user_id, updated)
        if error:
            raise ValueError(error)
        if not user["email_verified"]:
            user = self._data_manager.save(
                dict(user, email_verified=True))
        self._data_manager.set_state("verification", user_id, None)
        return user
