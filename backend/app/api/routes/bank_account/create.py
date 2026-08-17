from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.bank_account.schema import (
    BankAccountCreateSchema,
    BankAccountReadSchema,
)
from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services.bank_account_service import create_bank_account
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.services.bank_account_created_email import (
    send_bank_account_created_email,
)

logger = get_logger()

router = APIRouter(prefix="/bank-account")


@router.post(
    "/create", status_code=status.HTTP_201_CREATED, response_model=BankAccountReadSchema
)
async def create_bank_account_route(
    account_data: BankAccountCreateSchema,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    try:
        account = await create_bank_account(
            user_id=user.id, account_data=account_data, session=session
        )

        try:
            if not account.account_number:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Account number is not generated",
                )
            await send_bank_account_created_email(
                email=user.email,
                full_name=user.full_name,
                account_number=account.account_number,
                account_name=account.account_name,
                account_type=account.account_type,
                currency=account.currency,
                identification_type=user.profile.means_of_identification.value,
            )
        except Exception as e:
            logger.error(f"Failed to send bank account created email: {e}")

        logger.info(f"Bank account created: {account.account_number}")
        return account
    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        logger.error(f"Failed to create bank account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create bank account",
        )
