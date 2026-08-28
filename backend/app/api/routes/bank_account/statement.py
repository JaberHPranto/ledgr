from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.bank_account.enums import AccountStatusEnum
from backend.app.api.bank_account.models import BankAccount
from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services.transaction_service import generate_user_statement
from backend.app.api.transactions.schema import (
    StatementRequestSchema,
    StatementResponseSchema,
)
from backend.app.core.celery_app import celery_app
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger

logger = get_logger()

router = APIRouter(prefix="/bank-account")


@router.post(
    "/statement/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=StatementResponseSchema,
)
async def generate_statement(
    request: StatementRequestSchema,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    try:
        if request.start_date > request.end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Start date must be before end date",
            )

        if request.account_number:
            account_query = select(BankAccount).where(
                BankAccount.account_number == request.account_number,
                BankAccount.user_id == user.id,
            )
            account = await session.exec(account_query)
            account = account.first()

            if not account:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Account not found or not does not belong to the user",
                )

            if account.account_status != AccountStatusEnum.Active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot generate statement for inactive account",
                )

        result = await generate_user_statement(
            user_id=user.id,
            start_date=request.start_date,
            end_date=request.end_date,
            session=session,
            account_number=request.account_number,
        )

        celery_app.AsyncResult(result["task_id"])

        generated_at = datetime.now(timezone.utc)
        expires_at = generated_at + timedelta(hours=24)

        return StatementResponseSchema(
            status="pending",
            message="Statement generation is initiated",
            task_id=result["task_id"],
            statement_id=result["statement_id"],
            generated_at=generated_at,
            expires_at=expires_at,
        )

    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        logger.error(f"Failed to generate statement: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate statement",
        )


@router.get("/statement/{statement_id}")
async def get_statement(statement_id: str) -> Response:
    try:
        redis_client = celery_app.backend.client
        pdf_data = redis_client.get(f"statement:{statement_id}")

        if not pdf_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Statement not found",
            )

        return Response(
            content=pdf_data,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=statement_{statement_id}.pdf"
            },
        )

    except Exception as e:
        logger.error(f"Failed to get statement: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get statement",
        )
