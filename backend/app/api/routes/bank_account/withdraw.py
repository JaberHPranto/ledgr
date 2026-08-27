import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services.transaction_service import process_withdrawal
from backend.app.api.transactions.models import IdempotencyKey
from backend.app.api.transactions.schema import WithdrawalRequestSchema
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.services.withdrawal_alert import send_withdrawal_alert

logger = get_logger()
router = APIRouter(prefix="/bank-account")


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


@router.post("/withdraw", status_code=status.HTTP_201_CREATED)
async def create_withdrawal(
    withdrawal_data: WithdrawalRequestSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str = Header(
        description="Idempotency key for the withdrawal request"
    ),
):
    try:
        idempotency_key = validate_uuidv4(idempotency_key)
        if not idempotency_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency key in header is required",
            )
        existing_key_result = await session.exec(
            select(IdempotencyKey).where(
                IdempotencyKey.key == idempotency_key,
                IdempotencyKey.user_id == current_user.id,
                IdempotencyKey.endpoint == "/withdraw",
                IdempotencyKey.expires_at > datetime.now(timezone.utc),
            )
        )
        existing_key = existing_key_result.first()

        if existing_key:
            return {
                "status": "success",
                "message": "Withdrawal request already processed from cache",
                "data": existing_key.response_body,
            }

        transaction, account, user = await process_withdrawal(
            account_number=withdrawal_data.account_number,
            amount=withdrawal_data.amount,
            username=withdrawal_data.username,
            description=withdrawal_data.description,
            session=session,
        )

        try:
            await send_withdrawal_alert(
                email=user.email,
                full_name=user.full_name,
                amount=transaction.amount,
                account_name=account.account_name,
                account_number=account.account_number or "Unknown",
                currency=account.currency.value,
                description=transaction.description,
                transaction_date=transaction.completed_at or transaction.created_at,
                reference=transaction.reference,
                balance=Decimal(str(account.balance)),
            )
        except Exception as e:
            logger.error(f"Failed to send withdrawal alert: {e}")

        response = {
            "status": "success",
            "message": "Withdrawal processed successfully",
            "data": {
                "transaction_id": str(transaction.id),
                "reference": transaction.reference,
                "amount": str(transaction.amount),
                "balance": str(transaction.balance_after),
                "status": transaction.status.value,
            },
        }

        idempotency_record = IdempotencyKey(
            key=idempotency_key,
            user_id=user.id,
            endpoint="/withdraw",
            response_code=status.HTTP_201_CREATED,
            response_body=response,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        session.add(idempotency_record)
        await session.commit()

        return response

    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        logger.error(f"Failed to process withdrawal: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to process withdrawal"},
        )
