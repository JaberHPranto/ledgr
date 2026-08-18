import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.auth.schema import RoleChoicesSchema
from backend.app.api.bank_account.schema import (
    BankAccountReadSchema,
)
from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services import bank_account_service
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.services.account_activated_email import (
    send_account_activated_email,
)

logger = get_logger()

router = APIRouter(prefix="/bank-account")


@router.patch(
    "/{account_id}/activate",
    response_model=BankAccountReadSchema,
    status_code=status.HTTP_200_OK,
)
async def activate_bank_account(
    account_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    try:
        if current_user.role != RoleChoicesSchema.ACCOUNT_EXECUTIVE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only account executives can activate bank accounts.",
            )

        (
            activated_account,
            account_owner,
        ) = await bank_account_service.activate_bank_account(
            account_id, current_user.id, session
        )

        try:
            if not activated_account.account_number:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Account number is required to activate the bank account.",
                )
            await send_account_activated_email(
                email=account_owner.email,
                full_name=account_owner.full_name,
                account_number=activated_account.account_number,
                account_name=activated_account.account_name,
                account_type=activated_account.account_type.value,
                currency=activated_account.currency.value,
            )
            logger.info(f"Activation email sent to {account_owner.email}")
        except Exception as e:
            logger.error(e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
            )

        logger.info(
            f"Bank account {account_id} activated by account executive {current_user.email}"
        )
        return BankAccountReadSchema.model_validate(activated_account)

    except HTTPException:
        raise

    except Exception as e:
        logger.error(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
