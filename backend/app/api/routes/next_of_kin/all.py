from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.next_of_kin.schema import (
    NextOfKinReadSchema,
)
from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services.next_of_kin_service import get_user_next_of_kins
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger

logger = get_logger()

router = APIRouter(prefix="/next-of-kin")


@router.get("/all", response_model=list[NextOfKinReadSchema])
async def get_all_next_of_kins(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await get_user_next_of_kins(user.id, session)
        return result
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Failed to get all next of kin: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get all next of kin",
        )
