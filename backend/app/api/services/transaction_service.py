import uuid
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.auth.models import User
from backend.app.api.bank_account.enums import AccountStatusEnum
from backend.app.api.bank_account.models import BankAccount
from backend.app.api.transactions.enums import (
    TransactionCategoryEnum,
    TransactionStatusEnum,
    TransactionTypeEnum,
)
from backend.app.api.transactions.models import Transaction
from backend.app.core.logging import get_logger

logger = get_logger()


async def process_deposit(
    amount: Decimal,
    account_id: UUID,
    teller_id: UUID,
    description: str,
    session: AsyncSession,
) -> tuple[Transaction, BankAccount, User]:
    try:
        statement = (
            select(BankAccount, User).join(User).where(BankAccount.id == account_id)
        )
        result = await session.exec(statement)
        account_user = result.first()
        if not account_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
            )

        account, account_owner = account_user

        if not account.account_status == AccountStatusEnum.Active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Account is not active"
            )

        reference = f"DEP{uuid.uuid4().hex[:8].upper()}"

        balance_before = Decimal(str(account.balance))
        balance_after = balance_before + amount

        transaction = Transaction(
            amount=amount,
            description=description,
            reference=reference,
            transaction_type=TransactionTypeEnum.Deposit,
            transaction_category=TransactionCategoryEnum.Credit,
            status=TransactionStatusEnum.Pending,
            balance_before=balance_before,
            balance_after=balance_after,
            receiver_account_id=account_id,
            receiver_id=account_owner.id,
            processed_by=teller_id,
            transaction_metadata={
                "currency": account.currency,
                "account_number": account.account_number,
            },
        )

        teller = await session.get(User, teller_id)
        if teller:
            if transaction.transaction_metadata:
                transaction.transaction_metadata["teller_name"] = teller.full_name
                transaction.transaction_metadata["teller_email"] = teller.email

        account.balance = float(balance_after)

        session.add(transaction)
        session.add(account)
        await session.commit()

        await session.refresh(account)
        await session.refresh(transaction)

        return transaction, account, account_owner

    except HTTPException as http_ex:
        await session.rollback()
        raise http_ex
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to process deposit: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to process deposit"},
        )
