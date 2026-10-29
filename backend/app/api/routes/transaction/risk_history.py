from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.auth.schema import RoleChoicesSchema
from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services.transaction_service import get_user_risk_history
from backend.app.api.transactions.schema import (
    PaginatedHistoryResponseSchema,
    RiskHistoryItemSchema,
)
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger

logger = get_logger()
router = APIRouter(prefix="/transaction")


@router.get(
    "/risk-history",
    response_model=PaginatedHistoryResponseSchema,
    status_code=status.HTTP_200_OK,
    description="Get paginated risk analysis history for transactions. Only accessible to account executives.",
)
async def get_risk_history(
    current_user: CurrentUser,
    start_date: datetime | None = Query(
        default=None, description="Filter from this date"
    ),
    end_date: datetime | None = Query(
        default=None, description="Filter until this date"
    ),
    min_risk_score: float | None = Query(
        default=None, ge=0, le=1, description="Minimum risk score"
    ),
    user_id: str | None = Query(
        default=None,
        description="Filter by specific user ID (only for account executives)",
    ),
    offset: int = Query(
        default=0, ge=0, description="Number of records to skip(for pagination)"
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of records to return (for pagination)",
    ),
    session: AsyncSession = Depends(get_session),
) -> PaginatedHistoryResponseSchema:
    try:
        if current_user.role != RoleChoicesSchema.ACCOUNT_EXECUTIVE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "status": "error",
                    "message": "Only account executives can view transaction risk history",
                },
            )

        target_user_id = None

        if user_id:
            try:
                target_user_id = UUID(user_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "error",
                        "message": "Invalid user ID format",
                    },
                )
        else:
            target_user_id = current_user.id

        history_dicts, total_count = await get_user_risk_history(
            user_id=target_user_id,
            start_date=start_date,
            end_date=end_date,
            min_risk_score=min_risk_score,
            skip=offset,
            limit=limit,
            session=session,
        )

        history_items = [
            RiskHistoryItemSchema.model_validate(item) for item in history_dicts
        ]
        return PaginatedHistoryResponseSchema(
            total=total_count,
            offset=offset,
            limit=limit,
            items=history_items,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get risk history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to retrieve risk history",
                "action": "Please try again later",
            },
        )
