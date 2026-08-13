from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services import profile_service
from backend.app.api.user_profile.schema import ProfileResponseSchema
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger

router = APIRouter(prefix="/profile")

logger = get_logger()


@router.get("/me", response_model=ProfileResponseSchema)
async def get_me(user: CurrentUser, session: AsyncSession = Depends(get_session)):
    try:
        profile = await profile_service.get_user_with_profile(user.id, session)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
            )

        return profile
    except Exception as e:
        logger.error(f"Error fetching profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
