from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status

from backend.app.api.auth.schema import (
    PasswordResetConfirmSchema,
    PasswordResetRequestSchema,
)
from backend.app.api.services.user_service import user_auth_service
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.services.password_reset import send_password_reset_email

router = APIRouter(prefix="/auth")

logger = get_logger()


@router.post("/request-password-reset", status_code=status.HTTP_200_OK)
async def password_reset(
    reset_data: PasswordResetRequestSchema, session: AsyncSession = Depends(get_session)
):
    try:
        user = await user_auth_service.get_user_by_email(
            reset_data.email, session, include_inactive=True
        )

        if user:
            await send_password_reset_email(reset_data.email, user.id)
            return {"message": "Password reset link sent to your email"}

    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        logger.error(f"Failed to process password reset request: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to process password reset request"},
        )


@router.post("/reset-password/{token}", status_code=status.HTTP_200_OK)
async def reset_password(
    token: str,
    reset_data: PasswordResetConfirmSchema,
    session: AsyncSession = Depends(get_session),
):
    try:
        await user_auth_service.reset_password(
            token,
            reset_data.new_password,
            session,
        )
        return {"message": "Password has been reset successfully"}

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "error",
                "message": str(e),
                "action": "Please request a new password reset link.",
            },
        )
    except Exception as e:
        logger.error(f"Password reset failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to reset password.",
                "action": "Please try again later.",
            },
        )
