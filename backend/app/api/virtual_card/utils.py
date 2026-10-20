import calendar
import secrets
from datetime import date
from typing import Tuple

from argon2 import PasswordHasher


def generate_visa_card_number() -> str:
    prefix = "4"

    partial_number = prefix + "".join(secrets.choice("0123456789") for _ in range(14))

    total = 0

    # Applying the Luhn algorithm
    for i, digit in enumerate(partial_number):
        digit = int(digit)
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit

    checksum = (10 - total % 10) % 10

    return partial_number + str(checksum)


def generate_cvv() -> Tuple[str, str]:
    cvv = "".join(secrets.choice("0123456789") for _ in range(3))

    ph = PasswordHasher()

    cvv_hash = ph.hash(cvv)

    return cvv, cvv_hash


def verify_cvv(cvv: str, cvv_hash: str) -> bool:
    try:
        ph = PasswordHasher()
        return ph.verify(cvv_hash, cvv)
    except Exception:
        return False


def generate_card_expiry_date() -> date:
    # Cards are valid through the last day of the expiry month (MM/YY), 3 years out
    today = date.today()
    year = today.year + 3
    last_day = calendar.monthrange(year, today.month)[1]
    return date(year, today.month, last_day)
