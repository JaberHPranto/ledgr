import uuid

from fastapi import HTTPException
from sqlalchemy.orm import selectinload
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status

from backend.app.api.auth.models import User
from backend.app.api.auth.schema import RoleChoicesSchema
from backend.app.api.user_profile.enum import ImageTypeEnum
from backend.app.api.user_profile.models import Profile
from backend.app.api.user_profile.schema import (
    ProfileCreateSchema,
    ProfileUpdateSchema,
)
from backend.app.core.logging import get_logger
from backend.app.core.tasks import upload_image_task

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


def initiate_image_upload(
    file_content: bytes,
    image_type: ImageTypeEnum,
    content_type: str,
    user_id: uuid.UUID,
):
    try:
        task = upload_image_task.delay(  # type: ignore
            str(user_id), file_content, image_type.value, content_type
        )

        return task.id
    except Exception as e:
        logger.error(f"Error initiating image upload: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to initiate image upload",
            },
        )


async def upload_profile_image_url(
    user_id: uuid.UUID, image_type: ImageTypeEnum, image_url: str, session: AsyncSession
):
    try:
        profile = await get_user_profile(user_id, session)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "error",
                    "message": "User profile not found",
                },
            )

        field_mapping = {
            ImageTypeEnum.PROFILE_PHOTO: "profile_photo_url",
            ImageTypeEnum.ID_PHOTO: "id_photo_url",
            ImageTypeEnum.SIGNATURE_PHOTO: "signature_photo_url",
        }

        field_name = field_mapping[image_type]

        if not field_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "Invalid image type",
                },
            )

        setattr(profile, field_name, image_url)

        await session.commit()
        await session.refresh(profile)
        return profile

    except HTTPException as http_ex:
        raise http_ex

    except Exception as e:
        logger.error(f"Error uploading profile image: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to upload profile image",
            },
        )


async def get_user_with_profile(user_id: uuid.UUID, session: AsyncSession):
    try:
        statement = select(User).where(User.id == user_id)
        result = await session.exec(statement)
        user = result.first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "error",
                    "message": "User not found",
                },
            )

        await session.refresh(user, ["profile"])
        return user

    except Exception as e:
        logger.error(f"Error getting user with profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to get user with profile",
            },
        )


async def get_all_user_profiles(
    session: AsyncSession, current_user: User, offset: int = 0, limit: int = 10
) -> tuple[list[User], int]:
    try:
        if current_user.role != RoleChoicesSchema.BRANCH_MANAGER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "status": "error",
                    "message": "You do not have permission to view this resource",
                    "action": "Please contact your branch manager to request access",
                },
            )

        count_statement = select(func.count()).select_from(User)
        total_count = (await session.exec(count_statement)).one()

        statement = (
            select(User)
            .options(selectinload(User.profile))  # type: ignore
            .offset(offset)
            .limit(limit)
            .order_by(col(User.created_at).desc())
        )
        result = await session.exec(statement)
        users = result.all()

        return list(users), total_count

    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        logger.error(f"Error fetching all user profiles: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to fetch user profiles",
                "action": "Please try again later",
            },
        )
