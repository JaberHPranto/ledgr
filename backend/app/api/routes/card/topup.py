import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services.card import top_up_virtual_card
from backend.app.api.transactions.models import IdempotencyKey
from backend.app.api.virtual_card.schema import CardTopUpResponseSchema, CardTopUpSchema
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger

logger = get_logger()

router = APIRouter(prefix="/virtual-card")


def validate_uuidv4(value: str) -> str:
    try:
        uuid_obj = uuid.UUID(value)
        if uuid_obj.version != 4:
            raise ValueError("Not a valid UUID v4")
        return value
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Not a valid UUID v4"
        )


@router.post(
    "/{card_id}/top-up",
    response_model=CardTopUpResponseSchema,
    status_code=status.HTTP_200_OK,
    description="Top up a virtual card from a bank account. Card must be active",
)
async def top_up_card(
    card_id: UUID,
    top_up_data: CardTopUpSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str = Header(description="Idempotency key for the top-up request"),
) -> CardTopUpResponseSchema:
    try:
        idempotency_key = validate_uuidv4(idempotency_key)
        if not idempotency_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "Idempotency-Key header is required",
                },
            )

        existing_key_result = await session.exec(
            select(IdempotencyKey).where(
                IdempotencyKey.key == idempotency_key,
                IdempotencyKey.user_id == current_user.id,
                IdempotencyKey.endpoint == "/virtual-card/top-up",
                IdempotencyKey.expires_at > datetime.now(timezone.utc),
            )
        )

        existing_key = existing_key_result.first()

        if existing_key:
            return CardTopUpResponseSchema(
                status="success",
                message="Retrieved from cache",
                data=existing_key.response_body,
            )

        card, transaction = await top_up_virtual_card(
            card_id=card_id,
            account_number=top_up_data.account_number,
            amount=top_up_data.amount,
            description=top_up_data.description,
            session=session,
        )

        response = CardTopUpResponseSchema(
            status="success",
            message="Card topped up successfully",
            data={
                "card_id": str(card.id),
                "transaction_id": str(transaction.id),
                "amount": str(transaction.amount),
                "new_balance": str(card.available_balance),
                "reference": transaction.reference,
            },
        )

        idempotency_record = IdempotencyKey(
            key=idempotency_key,
            user_id=current_user.id,
            endpoint="/virtual-card/top-up",
            response_code=status.HTTP_200_OK,
            response_body=response.model_dump(),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        session.add(idempotency_record)
        await session.commit()

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to top up  card: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to top up card"},
        )
