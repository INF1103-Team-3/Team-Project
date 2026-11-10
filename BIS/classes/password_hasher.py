"""Password hashing compatible with the reference website hashes."""
import hashlib
import secrets
import re


class PasswordHasher:
    def create(self, password):
        if not isinstance(password, str) or not 6 <= len(password) <= 128:
            raise ValueError("Password must be 6–128 characters.")
        salt = secrets.token_hex(16)
        return {"password_salt": salt, "password_hash": self._hash(password, salt)}

    @staticmethod
    def _hash(password, salt):
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode("ascii"), 100000).hex()

    def verify(self, password, credential):
        if (not isinstance(credential.get("password_salt"), str)
                or not re.fullmatch(r"[0-9a-f]{32}", credential["password_salt"])
                or not isinstance(credential.get("password_hash"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", credential["password_hash"])):
            raise RuntimeError("Saved web credentials are invalid; restore the credential record.")
        return secrets.compare_digest(self._hash(password, credential["password_salt"]), credential["password_hash"])
