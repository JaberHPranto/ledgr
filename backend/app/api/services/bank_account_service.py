from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.auth.models import User
from backend.app.api.bank_account.enums import AccountStatusEnum
from backend.app.api.bank_account.models import BankAccount
from backend.app.api.bank_account.schema import BankAccountCreateSchema
from backend.app.api.bank_account.utils import generate_account_number
from backend.app.core.config import settings
from backend.app.core.logging import get_logger

logger = get_logger()


async def get_primary_bank_account(user_id: UUID, session: AsyncSession):
    query = select(BankAccount).where(
        BankAccount.user_id == user_id, BankAccount.is_primary
    )
    result = await session.exec(query)
    return result.first()


async def validate_user_kyc(user: User) -> bool:
    if not user.profile:
        return False

    if not user.next_of_kins or len(user.next_of_kins) == 0:
        return False

    return True


async def create_bank_account(
    user_id: UUID, account_data: BankAccountCreateSchema, session: AsyncSession
) -> BankAccount:
    try:
        statement = (
            select(User)
            .where(User.id == user_id)
            .options(
                selectinload(User.profile),  # type: ignore[arg-type]
                selectinload(User.next_of_kins),  # type: ignore[arg-type]
            )
        )
        result = await session.exec(statement)
        user = result.first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Check if the user has completed KYC
        if not await validate_user_kyc(user):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "User KYC not validated",
                    "action": "Please complete your profile and add at least one next of kin to create a bank account",
                },
            )

        # Check if the user already has the maximum number of bank accounts
        statement = select(BankAccount).where(BankAccount.user_id == user_id)
        result = await session.exec(statement)
        existing_bank_accounts = result.all()

        if len(existing_bank_accounts) >= settings.MAX_BANK_ACCOUNTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User already has the maximum number of bank accounts ({settings.MAX_BANK_ACCOUNTS})",
            )

        # Check if the user already has a primary bank account
        if account_data.is_primary:
            existing_primary_account = any(
                account.is_primary for account in existing_bank_accounts
            )

            if existing_primary_account:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "error",
                        "message": "A primary bank account already exists",
                        "action": "Please unset the existing primary account or remove it to create a new one",
                    },
                )

        elif len(existing_bank_accounts) == 0:
            account_data.is_primary = True

        account_number = generate_account_number(account_data.currency)

        bank_account = BankAccount(
            **account_data.model_dump(exclude={"account_number"}),
            user_id=user_id,
            account_number=account_number,
        )
        session.add(bank_account)
        await session.commit()
        await session.refresh(bank_account)
        return bank_account

    except HTTPException as http_ex:
        await session.rollback()
        raise http_ex

    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to create bank account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create bank account",
        )


async def activate_bank_account(
    account_id: UUID, verified_by: UUID, session: AsyncSession
) -> tuple[BankAccount, User]:
    try:
        statement = (
            select(BankAccount, User)
            .join(User)
            .where(BankAccount.id == account_id, BankAccount.user_id != verified_by)
        )
        result = await session.exec(statement)
        account_user_tuple = result.first()

        if not account_user_tuple:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bank account not found",
            )

        bank_account, user = account_user_tuple

        if bank_account.account_status == AccountStatusEnum.Active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bank account is already active",
            )

        bank_account.kyc_submitted = True
        bank_account.kyc_verified = True
        bank_account.kyc_verified_by = verified_by
        bank_account.kyc_verified_on = datetime.now(timezone.utc)
        bank_account.account_status = AccountStatusEnum.Active

        session.add(bank_account)
        await session.commit()
        await session.refresh(bank_account)

        return bank_account, user

    except HTTPException as http_ex:
        await session.rollback()
        raise http_ex

    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to activate bank account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to activate bank account",
        )
