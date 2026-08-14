from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.routes.auth.deps import CurrentUser
from backend.app.api.services import profile_service
from backend.app.api.user_profile.enum import ImageTypeEnum
from backend.app.core.celery_app import celery_app
from backend.app.core.db import get_session
from backend.app.core.logging import get_logger
from backend.app.core.utils.image import validate_image

router = APIRouter(prefix="/profile")

logger = get_logger()


@router.post("/upload/{image_type}", status_code=status.HTTP_202_ACCEPTED)
async def upload_profile_image(
    image_type: ImageTypeEnum,
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    try:
        file_content = await file.read()

        is_valid, error_message = validate_image(file_content)

        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": error_message,
                },
            )

        content_type = file.content_type or "application/octet-stream"

        task_id = profile_service.initiate_image_upload(
            file_content, image_type, content_type, current_user.id
        )

        return {
            "message": "Image upload initiated",
            "task_id": task_id,
            "status": "pending",
        }

    except HTTPException as http_ex:
        raise http_ex

    except Exception as e:
        logger.error(f"Error uploading profile image: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "An error occurred while uploading the image.",
            },
        )


@router.post("/upload/{task_id}/status", status_code=status.HTTP_200_OK)
async def check_upload_status(
    task_id: str,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    try:
        task = celery_app.AsyncResult(task_id)

        if task.ready():
            if task.successful():
                result = task.get()

                logger.debug(f"Task {task_id} succeeded: {result}")

                if not isinstance(result, dict):
                    raise ValueError(f"Unexpected result type: {type(result)}")

                if not result.get("url") or not result.get("image_type"):
                    raise ValueError(f"Missing required fields in result: {result}")

                await profile_service.upload_profile_image_url(
                    user_id=current_user.id,
                    image_type=ImageTypeEnum(result.get("image_type")),
                    image_url=str(result.get("url")),
                    session=session,
                )
                return {
                    "status": "completed",
                    "image_url": result["url"],
                    "thumbnail_url": result.get("thumbnail_url"),
                    "image_type": result["image_type"],
                }
            else:
                logger.error(f"Task {task_id} failed")
                error = str(task.result) if task.result else "Unknown error occurred"
                return {"status": "failed", "error": error}

        return {"status": "pending", "task_id": task_id}

    except ValueError as ve:
        logger.error(f"Validation error in upload status: {ve}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": str(ve)},
        )
    except Exception as e:
        logger.error(f"Failed to get upload status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to get upload status"},
        )
