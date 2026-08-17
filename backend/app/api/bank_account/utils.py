import secrets
from logging import getLogger

from fastapi import HTTPException
from starlette import status

from backend.app.api.bank_account.enums import AccountCurrencyEnum
from backend.app.core.config import settings

logger = getLogger()


def get_currency_code(currency: AccountCurrencyEnum):
    currency_code_mapper = {
        AccountCurrencyEnum.USD: settings.CURRENCY_CODE_USD,
        AccountCurrencyEnum.EUR: settings.CURRENCY_CODE_EUR,
        AccountCurrencyEnum.GBP: settings.CURRENCY_CODE_GBP,
    }

    currency_code = currency_code_mapper[currency]

    if not currency_code:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Currency code not found",
        )

    return currency_code


def split_into_digits(number: str) -> list[int]:
    return [int(digit) for digit in number]


# Calculate the checksum digit using Luhn Algorithm
def calculate_checksum_digit(number: str) -> int:
    digits = split_into_digits(number)

    odd_positioned_digits = digits[-1::-2]  # 12345 -> [5, 3, 1]
    even_positioned_digits = digits[-2::-2]  # 12345 -> [4, 2]

    total = sum(odd_positioned_digits)

    for digit in even_positioned_digits:
        doubled = digit * 2

        digits = split_into_digits(str(doubled))  # 12 -> [2, 1]
        total += sum(digits)  # 2 + 1 = 3

    # digit that rounds total up to the next multiple of 10; % 10 handles the already-multiple-of-10 case
    # Example: `total = 47` → `47 % 10 = 7` → `10 - 7 = 3` → check digit `3`, since `47 + 3 = 50` (multiple of 10)
    # total + checksum == should be a multiple of 10
    checksum = (10 - (total % 10)) % 10

    return checksum


# --- Bank Account Number (16 digits long) ---

#   3 digits -> Bank code
#   3 digits -> Branch code
#   2 digits -> Currency code
#   7 digits -> Random unique identifier
#   1 digit  -> Check digit for security [Created by Luhn Algorithm]

ACCOUNT_NUMBER_LENGTH = 16


def generate_account_number(currency: AccountCurrencyEnum) -> str:
    try:
        if not all([settings.BANK_CODE, settings.BANK_BRANCH_CODE]):
            raise HTTPException(
                status_code=500, detail="Bank code and branch code are not configured"
            )

        currency_code = get_currency_code(currency)

        prefix = f"{settings.BANK_CODE}{settings.BANK_BRANCH_CODE}{currency_code}"

        remaining_digits = (
            ACCOUNT_NUMBER_LENGTH - len(prefix) - 1
        )  # -1 for the checksum digit

        random_digits = "".join(
            secrets.choice("0123456789") for _ in range(remaining_digits)
        )

        partial_account_number = f"{prefix}{random_digits}"

        checksum_digit = calculate_checksum_digit(partial_account_number)

        account_number = f"{partial_account_number}{checksum_digit}"

        return account_number

    except HTTPException as http_ex:
        raise http_ex

    except Exception as e:
        logger.error(f"Failed to generate account number: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to generate account number",
                "details": str(e),
            },
        )
