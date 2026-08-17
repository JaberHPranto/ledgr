import uuid

from fastapi import HTTPException
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status

from backend.app.api.next_of_kin.models import NextOfKin
from backend.app.api.next_of_kin.schema import (
    NextOfKinCreateSchema,
    NextOfKinReadSchema,
    NextOfKinUpdateSchema,
)
from backend.app.core.logging import get_logger

logger = get_logger()

MAX_NEXT_OF_KIN = 3


async def get_next_of_kin_count(user_id: uuid.UUID, session: AsyncSession) -> int:
    query = (
        select(func.count())
        .select_from(NextOfKin)
        .where(
            NextOfKin.user_id == user_id,
        )
    )
    result = await session.exec(query)
    return result.one()


async def get_primary_next_of_kin(
    user_id: uuid.UUID, session: AsyncSession
) -> NextOfKin | None:
    query = select(NextOfKin).where(
        NextOfKin.user_id == user_id,
        NextOfKin.is_primary,
    )
    result = await session.exec(query)
    return result.one_or_none()


async def validate_next_of_kin_creation(
    user_id: uuid.UUID, is_primary: bool, session: AsyncSession
) -> int:
    count = await get_next_of_kin_count(user_id, session)
    if count >= MAX_NEXT_OF_KIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create more than 3 next of kin",
        )

    if is_primary:
        existing_primary = await get_primary_next_of_kin(user_id, session)
        if existing_primary:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create more than 1 primary next of kin",
            )

    return count


async def create_next_of_kin(
    user_id: uuid.UUID, next_of_kin_data: NextOfKinCreateSchema, session: AsyncSession
) -> NextOfKinReadSchema:
    try:
        current_count = await validate_next_of_kin_creation(
            user_id, next_of_kin_data.is_primary, session
        )

        if current_count == 0:
            next_of_kin_data.is_primary = True

        next_of_kin = NextOfKin(**next_of_kin_data.model_dump())
        next_of_kin.user_id = user_id

        session.add(next_of_kin)
        await session.commit()
        await session.refresh(next_of_kin)

        logger.info(f"Next of kin created: {next_of_kin.id}")
        return NextOfKinReadSchema.model_validate(next_of_kin)

    except HTTPException as http_ex:
        raise http_ex

    except Exception as e:
        logger.error(f"Failed to create next of kin: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to create next of kin"},
        )


async def get_user_next_of_kins(
    user_id: uuid.UUID, session: AsyncSession
) -> list[NextOfKinReadSchema]:
    try:
        query = select(NextOfKin).where(NextOfKin.user_id == user_id)
        result = await session.exec(query)
        next_of_kins = result.all()
        return [NextOfKinReadSchema.model_validate(kin) for kin in next_of_kins]

    except Exception as e:
        logger.error(f"Failed to get next of kin: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to get next of kin"},
        )


async def get_next_of_kin(
    user_id: uuid.UUID,
    next_of_kin_id: uuid.UUID,
    session: AsyncSession,
) -> NextOfKin:
    try:
        query = select(NextOfKin).where(
            NextOfKin.user_id == user_id,
            NextOfKin.id == next_of_kin_id,
        )
        result = await session.exec(query)
        next_of_kin = result.first()

        if not next_of_kin:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"status": "error", "message": "Next of kin not found"},
            )
        return next_of_kin

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Failed to get next of kin: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to get next of kin"},
        )


async def update_next_of_kin(
    user_id: uuid.UUID,
    next_of_kin_id: uuid.UUID,
    update_data: NextOfKinUpdateSchema,
    session: AsyncSession,
) -> NextOfKinReadSchema:
    try:
        next_of_kin = await get_next_of_kin(user_id, next_of_kin_id, session)

        if update_data.is_primary is not None:
            if update_data.is_primary:
                existing_primary = await get_primary_next_of_kin(user_id, session)
                if existing_primary:
                    existing_primary.is_primary = False
                    session.add(existing_primary)
                next_of_kin.is_primary = True
            else:
                total_count = await get_next_of_kin_count(user_id, session)
                if total_count == 1:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "status": "error",
                            "message": "Cannot unset primary next of kin when there is only one",
                        },
                    )
                next_of_kin.is_primary = False

        for key, value in update_data.model_dump(exclude_unset=True).items():
            setattr(next_of_kin, key, value)

        session.add(next_of_kin)
        await session.commit()
        await session.refresh(next_of_kin)

        return NextOfKinReadSchema.model_validate(next_of_kin)
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Failed to update next of kin: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to update next of kin"},
        )


async def delete_next_of_kin(
    user_id: uuid.UUID, next_of_kin_id: uuid.UUID, session: AsyncSession
) -> dict[str, str]:
    try:
        total_count = await get_next_of_kin_count(user_id, session)
        if total_count == 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "Cannot delete primary next of kin when there is only one",
                },
            )

        next_of_kin = await get_next_of_kin(user_id, next_of_kin_id, session)

        await session.delete(next_of_kin)
        await session.commit()

        logger.info(f"Deleted next of kin with id {next_of_kin_id}")
        return {"status": "success", "message": "Next of kin deleted successfully"}
    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        logger.error(f"Failed to delete next of kin: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to delete next of kin"},
        )
