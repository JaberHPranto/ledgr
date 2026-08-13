import io
from typing import Tuple

from PIL import Image, UnidentifiedImageError

from backend.app.core.config import settings
from backend.app.core.logging import get_logger

logger = get_logger()


def validate_image(file_data: bytes) -> Tuple[bool, str]:
    try:
        file_size_mb = len(file_data) / (1024 * 1024)
        max_file_size = settings.MAX_FILE_SIZE / (1024 * 1024)

        if file_size_mb > max_file_size:
            return False, f"File size exceeds maximum allowed size ({max_file_size} MB)"

        image_buffer = io.BytesIO(file_data)

        with Image.open(image_buffer) as img:
            if img.format is None or img.format.lower() not in ["jpeg", "png", "jpg"]:
                return False, "Unsupported image format"

            width, height = img.size
            if width > settings.MAX_DIMENSIONS or height > settings.MAX_DIMENSIONS:
                return (
                    False,
                    f"Image dimensions exceed {settings.MAX_DIMENSIONS}px limit",
                )

            try:
                img.verify()
            except Exception as e:
                return False, f"Invalid image file: {str(e)}"

            return True, "Image is valid"

    except UnidentifiedImageError:
        return False, "File is not a valid image"
    except Exception as e:
        logger.error(f"Image validation error: {str(e)}")
        return False, f"Invalid image file: {str(e)}"
