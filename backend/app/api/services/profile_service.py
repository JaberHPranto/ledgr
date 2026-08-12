import uuid

from fastapi import HTTPException
from sqlalchemy.sql.functions import user
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status

from backend.app.api.user_profile.models import Profile
from backend.app.api.user_profile.schema import ProfileCreateSchema, ProfileUpdateSchema
from backend.app.core.logging import get_logger

logger = get_logger()


async def get_user_profile(user_id: uuid.UUID, session: AsyncSession):
    try:
        statement = select(Profile).where(Profile.user_id == user_id)
        user_profile = await session.exec(statement)
        return user_profile.first()
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to get user profile",
            },
        )


async def create_user_profile(
    user_id: uuid.UUID, profile_data: ProfileCreateSchema, session: AsyncSession
):
    try:
        is_profile_exists = await get_user_profile(user_id, session)

        if is_profile_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "User profile already exists",
                },
            )

        profile = Profile(user_id=user_id, **profile_data.model_dump())
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
        return profile

    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        logger.error(f"Error creating user profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to create user profile",
            },
        )


async def update_user_profile(
    user_id: uuid.UUID, profile_data: ProfileUpdateSchema, session: AsyncSession
):
    try:
        profile = await get_user_profile(user_id, session)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "error",
                    "message": "User profile not found",
                    "action": "Please create a profile first",
                },
            )
        updated_profile = profile_data.model_dump(exclude_unset=True)
        for key, value in updated_profile.items():
            setattr(profile, key, value)
        await session.commit()
        await session.refresh(profile)

        logger.info(f"Updated profile for user {user_id}")
        return profile
    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        logger.error(f"Error updating user profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to update user profile",
            },
        )
