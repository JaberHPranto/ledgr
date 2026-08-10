from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status

from backend.app.api.auth.schema import UserCreateSchema, UserReadSchema
from backend.app.api.services.user_service import user_auth_service
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger

router = APIRouter(prefix="/auth")

logger = get_logger()


@router.post(
    "/register", response_model=UserReadSchema, status_code=status.HTTP_201_CREATED
)
async def register_user(
    user_data: UserCreateSchema, session: AsyncSession = Depends(get_session)
):
    try:
        if await user_auth_service.check_user_email_exists(user_data.email, session):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists",
            )

        if await user_auth_service.check_user_id_no_exists(user_data.id_no, session):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this ID number already exists",
            )

        user = await user_auth_service.create_user(user_data, session)
        return user

    except HTTPException as http_ex:
        await session.rollback()
        raise http_ex
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to register user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
