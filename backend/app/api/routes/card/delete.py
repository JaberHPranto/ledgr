from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services.card import delete_virtual_card
from backend.app.api.virtual_card.schema import CardDeleteResponseSchema
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger

logger = get_logger()
router = APIRouter(prefix="/virtual-card")


@router.delete(
    "/{card_id}",
    response_model=CardDeleteResponseSchema,
    status_code=status.HTTP_200_OK,
    description="Delete a virtual card. Card must have zero balance and no physical card request",
)
async def delete_card(
    card_id: UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> CardDeleteResponseSchema:
    try:
        result = await delete_virtual_card(
            card_id=card_id, user_id=current_user.id, session=session
        )

        return CardDeleteResponseSchema(
            status="success",
            message="Virtual card deleted successfully",
            deleted_at=result["deleted_at"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete  card: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to delete virtual card"},
        )
