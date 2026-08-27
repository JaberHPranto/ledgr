import uuid
from datetime import datetime, timezone
from logging import getLogger
from typing import Optional

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status

from backend.app.api.transactions.enums import (
    TransactionFailureReason,
    TransactionStatusEnum,
)
from backend.app.api.transactions.models import Transaction

logger = getLogger()


async def mark_transaction_failed(
    transaction: Transaction,
    reason: TransactionFailureReason,
    details: dict,
    session: AsyncSession,
    error_message: Optional[str] = None,
):
    try:
        transaction.status = TransactionStatusEnum.Failed
        transaction.failed_reason = reason

        current_metadata = transaction.transaction_metadata or {}

        failure_details = {
            "reason": reason.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_message": error_message,
            **details,
        }

        transaction.transaction_metadata = {
            **current_metadata,
            "failure_details": failure_details,
        }

        session.add(transaction)
        await session.commit()
        await session.refresh(transaction)

        logger.info(
            f"Transaction {transaction.id} marked as failed",
            extra={
                "reference": transaction.reference,
                "reason": reason.value,
                "details": failure_details,
            },
        )
    except Exception as e:
        logger.error(f"Failed to mark transaction failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


def generate_transaction_reference(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"
