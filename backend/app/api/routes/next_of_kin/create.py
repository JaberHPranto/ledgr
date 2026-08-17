from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.next_of_kin.schema import (
    NextOfKinCreateSchema,
    NextOfKinReadSchema,
)
from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services.next_of_kin_service import create_next_of_kin
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger

logger = get_logger()

router = APIRouter(prefix="/next-of-kin")


@router.post(
    "/create", status_code=status.HTTP_201_CREATED, response_model=NextOfKinReadSchema
)
async def create_next_of_kin_route(
    next_of_kin_data: NextOfKinCreateSchema,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    try:
        next_of_kin = await create_next_of_kin(
            user_id=current_user.id, next_of_kin_data=next_of_kin_data, session=session
        )
        return next_of_kin
    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        logger.error(f"Failed to create next of kin: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create next of kin",
        )
