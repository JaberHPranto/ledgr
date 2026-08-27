import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services.transaction_service import (
    complete_transfer,
    initiate_transfer,
)
from backend.app.api.transactions.models import IdempotencyKey
from backend.app.api.transactions.schema import (
    TransferOTPVerificationSchema,
    TransferRequestSchema,
    TransferResponseSchema,
)
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.services.transfer_alert import send_transfer_alert_email
from backend.app.core.services.transfer_otp import send_transfer_otp_email
from backend.app.core.utils.format_number import format_currency

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


@router.post(
    "/transfer/initiate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TransferResponseSchema,
)
async def initiate_money_transfer(
    transfer_data: TransferRequestSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str = Header(
        None, description="Idempotency key for the transfer request"
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
                IdempotencyKey.endpoint == "/transfer/initiate",
                IdempotencyKey.expires_at > datetime.now(timezone.utc),
            )
        )
        existing_key = existing_key_result.first()
        if existing_key:
            return TransferResponseSchema(
                status="success",
                message="Idempotent key found. Retrieve from cache",
                data=existing_key.response_body,
            )

        (
            transaction,
            sender_account,
            receiver_account,
            sender,
            receiver,
        ) = await initiate_transfer(
            sender_id=current_user.id,
            sender_account_id=transfer_data.sender_account_id,
            receiver_account_number=transfer_data.receiver_account_number,
            amount=transfer_data.amount,
            description=transfer_data.description,
            security_answer=transfer_data.security_answer,
            session=session,
        )

        try:
            await send_transfer_otp_email(sender.email, sender.otp)
        except Exception as e:
            logger.error("Failed to send transfer OTP email: " + str(e))

        response = TransferResponseSchema(
            status="success",
            message="Transfer initiated successfully",
            data={
                "reference": transaction.reference,
                "amount": format_currency(str(transaction.amount)),
                "converted_amount": (
                    transaction.transaction_metadata.get("converted_amount", "N/A")
                    if transaction.transaction_metadata
                    else "N/A"
                ),
                "from_currency": (
                    transaction.transaction_metadata.get("from_currency", "N/A")
                    if transaction.transaction_metadata
                    else "N/A"
                ),
                "to_currency": (
                    transaction.transaction_metadata.get("to_currency", "N/A")
                    if transaction.transaction_metadata
                    else "N/A"
                ),
            },
        )

        idempotency_record = IdempotencyKey(
            key=idempotency_key,
            user_id=current_user.id,
            endpoint="/transfer/initiate",
            response_code=status.HTTP_202_ACCEPTED,
            response_body=response.model_dump(),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        session.add(idempotency_record)
        await session.commit()

        return response

    except HTTPException as http_ex:
        raise http_ex

    except Exception as e:
        logger.error(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post(
    "/transfer/complete",
    response_model=TransferResponseSchema,
    status_code=status.HTTP_200_OK,
)
async def complete_money_transfer(
    verification_data: TransferOTPVerificationSchema,
    session: AsyncSession = Depends(get_session),
):
    try:
        (
            transaction,
            sender_account,
            receiver_account,
            sender,
            receiver,
        ) = await complete_transfer(
            reference=verification_data.transfer_reference,
            otp=verification_data.otp,
            session=session,
        )

        try:
            await send_transfer_alert_email(
                sender_email=sender.email,
                receiver_email=receiver.email,
                sender_name=sender.full_name,
                receiver_name=receiver.full_name,
                sender_account_number=sender_account.account_number or "Unknown",
                receiver_account_number=receiver_account.account_number or "Unknown",
                amount=transaction.amount,
                converted_amount=(
                    Decimal(
                        transaction.transaction_metadata.get("converted_amount", "0")
                    )
                    if transaction.transaction_metadata
                    else Decimal("0")
                ),
                sender_currency=sender_account.currency,
                receiver_currency=receiver_account.currency,
                exchange_rate=(
                    Decimal(
                        transaction.transaction_metadata.get("conversion_rate", "1")
                    )
                    if transaction.transaction_metadata
                    else Decimal("1")
                ),
                conversion_fee=(
                    Decimal(transaction.transaction_metadata.get("conversion_fee", "0"))
                    if transaction.transaction_metadata
                    else Decimal("0")
                ),
                description=transaction.description,
                reference=transaction.reference,
                transaction_date=transaction.completed_at or transaction.created_at,
                sender_balance=Decimal(sender_account.balance),
                receiver_balance=Decimal(receiver_account.balance),
            )
        except Exception as e:
            logger.error(f"Failed to send transfer alerts: {e}")

        return TransferResponseSchema(
            status="success",
            message="Transfer completed successfully",
            data={
                "reference": transaction.reference,
                "amount": format_currency(str(transaction.amount)),
                "converted_amount": (
                    transaction.transaction_metadata.get("converted_amount", "N/A")
                    if transaction.transaction_metadata
                    else "N/A"
                ),
                "from_currency": (
                    transaction.transaction_metadata.get("from_currency", "N/A")
                    if transaction.transaction_metadata
                    else "N/A"
                ),
                "to_currency": (
                    transaction.transaction_metadata.get("to_currency", "N/A")
                    if transaction.transaction_metadata
                    else "N/A"
                ),
            },
        )

    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        logger.error(f"Failed to complete transfer: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to complete transfer"},
        )
