from datetime import datetime, timezone
from decimal import Decimal
from typing import Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.auth.models import User
from backend.app.api.auth.schema import RoleChoicesSchema
from backend.app.api.bank_account.enums import AccountStatusEnum
from backend.app.api.bank_account.models import BankAccount
from backend.app.api.transactions.enums import (
    TransactionCategoryEnum,
    TransactionStatusEnum,
    TransactionTypeEnum,
)
from backend.app.api.transactions.models import Transaction
from backend.app.api.transactions.utils import generate_transaction_reference
from backend.app.api.virtual_card.enums import VirtualCardStatusEnum
from backend.app.api.virtual_card.models import VirtualCard
from backend.app.api.virtual_card.utils import (
    generate_card_expiry_date,
    generate_cvv,
    generate_visa_card_number,
)
from backend.app.core.logging import get_logger

logger = get_logger()


async def create_virtual_card(
    user_id: UUID, bank_account_id: UUID, card_data: dict, session: AsyncSession
) -> Tuple[VirtualCard, User, BankAccount]:
    try:
        stmt = (
            select(BankAccount, User)
            .join(User)
            .where(BankAccount.id == bank_account_id, BankAccount.user_id == user_id)
        )

        result = await session.exec(stmt)
        account_user = result.first()

        if not account_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
            )

        bank_account, user = account_user

        if bank_account.account_status != AccountStatusEnum.Active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Account is not active"
            )

        card_currency = card_data.get("currency")

        if card_currency != bank_account.currency:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Currency does not match with bank account currency",
            )

        cleaned_data = card_data.copy()

        cleaned_data.pop("card_number", None)
        cleaned_data.pop("card_status", None)
        cleaned_data.pop("is_active", None)
        cleaned_data.pop("cvv_hash", None)
        cleaned_data.pop("available_balance", None)
        cleaned_data.pop("total_topped_up", None)
        cleaned_data.pop("card_metadata", None)

        card_number = generate_visa_card_number()

        if not cleaned_data.get("expiry_date"):
            cleaned_data["expiry_date"] = generate_card_expiry_date()

        card = VirtualCard(
            **cleaned_data,
            card_number=card_number,
            bank_account_id=bank_account_id,
            card_status=VirtualCardStatusEnum.Pending,
            is_active=True,
            available_balance=0.0,
            total_topped_up=0.0,
            last_top_up_date=datetime.now(timezone.utc),
            card_metadata={
                "created_by": str(user.id),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        session.add(card)
        await session.commit()
        await session.refresh(card)

        return card, user, bank_account

    except Exception as e:
        await session.rollback()
        logger.error("Failed to create virtual card: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "Failed to create virtual card",
                "error": str(e),
            },
        )


async def block_virtual_card(
    card_id: UUID, block_data: dict, blocked_by: UUID, session: AsyncSession
) -> Tuple[VirtualCard, User]:
    try:
        stmt = (
            select(VirtualCard, User)
            .select_from(VirtualCard)
            .join(BankAccount)
            .join(User)
            .where(VirtualCard.id == card_id)
        )
        result = await session.exec(stmt)
        card_data = result.first()

        if not card_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "message": "Virtual card not found",
                },
            )

        card, card_owner = card_data

        if card.card_status == VirtualCardStatusEnum.Blocked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Virtual card is already blocked",
                },
            )

        block_time = datetime.now(timezone.utc)
        card.card_status = VirtualCardStatusEnum.Blocked
        card.block_reason = block_data["block_reason"]
        card.block_reason_description = block_data["block_reason_description"]
        card.blocked_by = blocked_by
        card.blocked_at = block_time

        if not card.card_metadata:
            card.card_metadata = {}

        card.card_metadata.update(
            {
                "blocked_at": block_time.isoformat(),
                "blocked_by": str(blocked_by),
                "block_reason": block_data["block_reason"].value,
            }
        )

        session.add(card)
        await session.commit()
        await session.refresh(card)

        return card, card_owner

    except Exception as e:
        await session.rollback()
        logger.error("Failed to block virtual card: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "Failed to block virtual card",
                "error": str(e),
            },
        )


async def top_up_virtual_card(
    card_id: UUID,
    account_number: str,
    amount: float,
    description: str,
    session: AsyncSession,
) -> Tuple[VirtualCard, Transaction]:
    try:
        stmt = (
            select(VirtualCard, BankAccount)
            .join(BankAccount)
            .where(
                VirtualCard.id == card_id, BankAccount.account_number == account_number
            )
        )
        result = await session.exec(stmt)
        card_account = result.first()

        if not card_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "message": "Card or account not found",
                },
            )

        card, bank_account = card_account

        if card.card_status != VirtualCardStatusEnum.Active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Card is not active",
                },
            )

        if bank_account.account_status != AccountStatusEnum.Active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Bank account is not active",
                },
            )

        if Decimal(str(amount)) > Decimal(str(bank_account.balance)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Insufficient balance",
                },
            )

        if card.currency != bank_account.currency:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Currency mismatch",
                },
            )

        reference = generate_transaction_reference("TOPUP")

        balance_before = Decimal(str(bank_account.balance))
        balance_after = balance_before - Decimal(str(amount))

        current_time = datetime.now(timezone.utc)

        transaction = Transaction(
            amount=Decimal(str(amount)),
            description=description,
            reference=reference,
            transaction_type=TransactionTypeEnum.Transfer,
            transaction_category=TransactionCategoryEnum.Debit,
            status=TransactionStatusEnum.Completed,
            balance_before=balance_before,
            balance_after=balance_after,
            sender_account_id=bank_account.id,
            sender_id=bank_account.user_id,
            completed_at=current_time,
            transaction_metadata={
                "top_up_type": "virtual_card",
                "card_id": str(card.id),
                "card_last_four": card.last_four_digits,
                "currency": card.currency.value,
            },
        )

        bank_account.balance = float(balance_after)
        card.available_balance += amount
        card.total_topped_up += amount
        card.last_top_up_date = current_time

        session.add(transaction)
        session.add(bank_account)
        session.add(card)

        await session.commit()

        await session.refresh(card)
        await session.refresh(transaction)

        return card, transaction

    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to top up virtual card: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "Failed to top up virtual card",
                "error": str(e),
            },
        )


async def activate_virtual_card(
    card_id: UUID, activated_by: UUID, session: AsyncSession
) -> tuple[VirtualCard, User, str]:
    try:
        stmt = (
            select(VirtualCard, BankAccount, User)
            .select_from(VirtualCard)
            .join(BankAccount)
            .join(User)
            .where(VirtualCard.id == card_id)
        )
        result = await session.exec(stmt)
        card_data = result.first()

        if not card_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "message": "Virtual card not found",
                },
            )

        card, bank_account, card_owner = card_data

        executive = await session.get(User, activated_by)

        if not executive or executive.role != RoleChoicesSchema.ACCOUNT_EXECUTIVE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": "Only account executives can activate virtual cards",
                },
            )

        if card.card_status == VirtualCardStatusEnum.Active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Virtual card is already active",
                },
            )

        new_cvv, cvv_hash = generate_cvv()

        card.card_status = VirtualCardStatusEnum.Active
        card.cvv_hash = cvv_hash

        if not card.card_metadata:
            card.card_metadata = {}

        card.card_metadata.update(
            {
                "activated_by": activated_by,
                "activated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        session.add(card)
        await session.commit()
        await session.refresh(card)

        return card, card_owner, new_cvv

    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to activate virtual card: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "Failed to activate virtual card",
                "error": str(e),
            },
        )


async def delete_virtual_card(
    card_id: UUID, user_id: UUID, session: AsyncSession
) -> dict:
    try:
        stmt = (
            select(VirtualCard, User)
            .join(BankAccount, col(BankAccount.id) == col(VirtualCard.bank_account_id))
            .join(User, col(User.id) == col(BankAccount.user_id))
            .where(VirtualCard.id == card_id, User.id == user_id)
        )
        result = await session.exec(stmt)
        card_account = result.first()

        if not card_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "message": "Virtual card not found",
                },
            )

        card, _ = card_account

        if card.physical_card_requested_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Cannot delete a card that has a physical card requested",
                },
            )

        if card.available_balance > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Please withdraw remaining balance first",
                },
            )

        deletion_time = datetime.now(timezone.utc)
        existing_metadata = card.card_metadata or {}

        new_metadata = {
            **existing_metadata,
            "deleted_at": deletion_time.isoformat(),
            "deletion_reason": "user_requested",
            "deleted_by": str(user_id),
            "card_status_before_deletion": card.card_status.value,
            "deletion_timestamp": deletion_time.timestamp(),
        }

        card.card_metadata = new_metadata
        card.is_active = False

        session.add(card)
        await session.commit()
        await session.refresh(card)

        logger.info(
            f"Virtual card {card_id} soft deleted successfully",
        )
        return {
            "status": "success",
            "message": "Virtual card deleted successfully",
            "deleted_at": deletion_time,
        }

    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to delete virtual card: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "Failed to delete virtual card",
                "error": str(e),
            },
        )
