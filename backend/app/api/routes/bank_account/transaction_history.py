from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services.transaction_service import get_user_transactions
from backend.app.api.transactions.schema import (
    PaginatedTransactionResponseSchema,
    TransactionFilterParamsSchema,
    TransactionHistoryResponseSchema,
)
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger

logger = get_logger()
router = APIRouter(prefix="/transactions")


@router.get(
    "/history",
    status_code=status.HTTP_200_OK,
    response_model=PaginatedTransactionResponseSchema,
)
async def get_transaction_history(
    current_user: CurrentUser,
    filters: Annotated[TransactionFilterParamsSchema, Query()],
    session: AsyncSession = Depends(get_session),
):
    try:
        if (
            filters.start_date
            and filters.end_date
            and filters.start_date > filters.end_date
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date must be before end_date",
            )

        transactions, total_count = await get_user_transactions(
            user_id=current_user.id,
            session=session,
            limit=filters.limit,
            offset=filters.offset,
            start_date=filters.start_date,
            end_date=filters.end_date,
            transaction_type=filters.transaction_type,
            transaction_category=filters.transaction_category,
            transaction_status=filters.status,
            min_amount=filters.min_amount,
            max_amount=filters.max_amount,
        )

        transaction_responses = []

        for txn in transactions:
            metadata = txn.transaction_metadata or {}

            response = TransactionHistoryResponseSchema(
                id=txn.id,
                reference=txn.reference,
                amount=txn.amount,
                description=txn.description,
                transaction_type=txn.transaction_type,
                transaction_category=txn.transaction_category,
                transaction_status=txn.status,
                created_at=txn.created_at,
                completed_at=txn.completed_at,
                balance_after=txn.balance_after,
                currency=metadata.get("currency"),
                converted_amount=metadata.get("converted_amount"),
                from_currency=metadata.get("from_currency"),
                to_currency=metadata.get("to_currency"),
                counterparty_name=metadata.get("counterparty_name"),
                counterparty_account=metadata.get("counterparty_account"),
            )
            transaction_responses.append(response)

        return PaginatedTransactionResponseSchema(
            total=total_count,
            offset=filters.offset,
            limit=filters.limit,
            transactions=transaction_responses,
        )
    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        logger.error(f"Error retrieving transaction history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to retrieve transaction history",
                "action": "Please try again later",
            },
        )
