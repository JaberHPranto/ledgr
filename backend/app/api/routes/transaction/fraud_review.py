from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.auth.schema import RoleChoicesSchema
from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services.transaction_service import review_flagged_transactions
from backend.app.api.transactions.schema import TransactionReviewSchema
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger

logger = get_logger()
router = APIRouter(prefix="/transaction")


@router.post(
    "/{transaction_id}/review",
    status_code=status.HTTP_200_OK,
    description="Review a flagged transaction. Only available to account executives",
)
async def review_transaction(
    transaction_id: UUID,
    review_data: TransactionReviewSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        if current_user.role != RoleChoicesSchema.ACCOUNT_EXECUTIVE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only account executives can review transactions",
            )

        result = await review_flagged_transactions(
            transaction_id=transaction_id,
            reviewer_id=current_user.id,
            session=session,
            is_fraud=review_data.is_fraud,
            notes=review_data.notes,
            approve_transaction=review_data.approve_transaction,
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to review transaction: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to review transaction",
                "action": "Please try again later",
            },
        )
