from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status

from backend.app.api.auth.schema import AccountStatusSchema, EmailRequestSchema
from backend.app.api.auth.utils import generate_activation_token
from backend.app.api.services.user_service import user_auth_service
from backend.app.core.config import settings
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.services.activation_email import send_activation_email

router = APIRouter(prefix="/auth")

logger = get_logger()


@router.get("/activate/{token}")
async def activate_user(token: str, session: AsyncSession = Depends(get_session)):
    try:
        user = await user_auth_service.activate_user(token, session)
        return {"message": "User activated successfully", "email": user.email}

    except ValueError as e:
        error_msg = str(e)

        if error_msg == "Activation token expired":
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={
                    "status": "error",
                    "message": "Activation link has expired",
                    "action": "Please request a new activation link",
                    "action_url": f"{settings.API_BASE_URL}{settings.API_V1}/auth/resend-activation-link",
                    "email_required": True,
                },
            )

        elif error_msg == "Invalid activation token":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "Invalid activation token",
                    "action": "Please confirm that the link you clicked on is correct",
                },
            )

        elif error_msg == "User already activated":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "User already activated",
                    "action": "Please login to your account",
                },
            )
    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        logger.error(f"Failed to activate user account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to activate user account",
                "action": "Please try again later",
            },
        )


@router.post("/resend-activation-link")
async def resend_activation_link(
    email_data: EmailRequestSchema, session: AsyncSession = Depends(get_session)
):
    try:
        user = await user_auth_service.get_user_by_email(
            email_data.email, session, include_inactive=True
        )
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "error",
                    "message": "User not found",
                    "action": "Please check your email and try again",
                },
            )
        if user.is_active or user.account_status == AccountStatusSchema.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "User already activated",
                    "action": "Please login to your account",
                },
            )

        activation_token = generate_activation_token(user.id)
        await send_activation_email(user.email, activation_token)

        return {
            "status": "success",
            "message": "Activation link has been resent",
            "action": "Please check your email",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resend activation link: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to resend activation link",
                "action": "Please try again later",
            },
        )
