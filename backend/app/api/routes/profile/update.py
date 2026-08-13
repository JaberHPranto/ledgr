from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services import profile_service
from backend.app.api.user_profile.models import Profile
from backend.app.api.user_profile.schema import ProfileUpdateSchema
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger

router = APIRouter(prefix="/profile")

logger = get_logger()


@router.patch("/update", response_model=Profile, status_code=status.HTTP_200_OK)
async def update_profile(
    profile_data: ProfileUpdateSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    try:
        updated_profile = await profile_service.update_user_profile(
            user_id=current_user.id,
            profile_data=profile_data,
            session=session,
        )
        logger.info(f"Profile updated for the user {current_user.id}")
        return updated_profile
    except Exception as e:
        logger.error(f"Failed to update profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile",
        )
