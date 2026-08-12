import jwt
from amqp.connection import uuid
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.auth.utils import create_jwt_token, set_auth_cookies
from backend.app.api.services.user_service import user_auth_service
from backend.app.core.config import settings
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger

router = APIRouter(prefix="/auth")

logger = get_logger()


@router.post("/refresh")
async def refresh_access_token(
    response: Response,
    session: AsyncSession = Depends(get_session),
    refresh_token: str | None = Cookie(None, alias=settings.COOKIE_REFRESH_NAME),
) -> dict:
    try:
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token not provided",
            )

        try:
            payload = jwt.decode(
                refresh_token,
                settings.SIGNING_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )

            if payload.get("type") != settings.COOKIE_REFRESH_NAME:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type",
                )

            user_id = uuid.UUID(payload.get("id"))
            user = await user_auth_service.get_user_by_id(user_id, session)

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found",
                )

            await user_auth_service.validate_user_status(user)

            access_token = create_jwt_token(user.id)
            refresh_token = create_jwt_token(user.id, type=settings.COOKIE_REFRESH_NAME)

            set_auth_cookies(response, access_token, refresh_token)

            logger.info(f"Successfully refreshed access token for user {user.email}")
            return {
                "message": "Access token refreshed successfully",
                "user": {
                    "email": user.email,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "full_name": user.full_name,
                    "id_no": user.id_no,
                    "role": user.role,
                },
            }

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "status": "error",
                    "message": "Refresh token has expired",
                    "action": "Please login again",
                },
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "status": "error",
                    "message": "Invalid refresh token",
                    "action": "Please login again",
                },
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to refresh the token",
                "action": "Please try again later",
            },
        )
