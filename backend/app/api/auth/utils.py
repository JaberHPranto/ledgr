import random
import string

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from backend.app.core.config import settings

_ph = PasswordHasher()

USERNAME_LENGTH = 12


def generate_otp(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False


def generate_username() -> str:
    bank_name = settings.SITE_NAME
    words = bank_name.split()
    prefix = "".join([word[0] for word in words]).upper()

    remaining_length = USERNAME_LENGTH - len(prefix) - 1
    suffix = "".join(
        random.choices(string.ascii_uppercase + string.digits, k=remaining_length)
    )
    return f"{prefix}-{suffix}"
