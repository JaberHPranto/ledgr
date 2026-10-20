from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services.card import activate_virtual_card
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.services.card_activated import send_card_activated_email

logger = get_logger()
router = APIRouter(prefix="/virtual-card")


@router.patch(
    "/{card_id}/activate",
    status_code=status.HTTP_200_OK,
    description="Activate a virtual card. Only account executives can perform this action",
)
async def activate_card(
    card_id: UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    try:
        card, card_owner, cvv = await activate_virtual_card(
            card_id, current_user.id, session
        )

        try:
            await send_card_activated_email(
                email=card_owner.email,
                full_name=card_owner.full_name,
                card_type=card.card_type.value,
                currency=card.currency.value,
                masked_card_number=card.masked_card_number,
                cvv=cvv,
                expiry_date=card.expiry_date.strftime("%m/%Y")
                if card.expiry_date
                else "N/A",
                daily_limit=card.daily_limit,
                monthly_limit=card.monthly_limit,
                available_balance=card.available_balance,
            )
        except Exception as email_error:
            logger.error(f"Failed to send card activation email: {email_error}")

        return {
            "status": "success",
            "message": "Card activated successfully",
            "data": {
                "card_id": str(card.id),
                "status": card.card_status.value,
                "activated_at": (
                    card.card_metadata.get("activated_at")
                    if card.card_metadata
                    else None
                ),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to activate virtual card: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to activate virtual card"},
        )
