"""Authorization rules shared by CLI and web profile updates."""


class ProfileAccessPolicy:
    """Keep account ownership and email verification decisions in Logic."""

    @staticmethod
    def check_owner(user, payload):
        if payload.get("user_id") not in (None, user["userID"]):
            raise PermissionError("A profile can only be changed by its owner.")
        if payload.get("email") not in (None, user["email"]):
            raise ValueError(
                "Changing the verified email is not supported by this profile form.")

    @staticmethod
    def require_verified(user, smtp_bypass=False, error_type=PermissionError):
        if not user["email_verified"] and smtp_bypass is not True:
            raise error_type("Verify your email before changing preferences.")
