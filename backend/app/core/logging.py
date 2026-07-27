import os

from app.core.config import settings
from loguru import logger

# removing default logger
logger.remove()

# adding custom logger
LOG_DIR = os.path.join(
    # `/backend/app/logs.py`
    os.path.dirname(os.path.dirname(__file__)),
    "logs",
)

LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
)

# DEBUG logger
logger.add(
    sink=os.path.join(LOG_DIR, "debug.log"),
    format=LOG_FORMAT,
    level="DEBUG"
    if settings.Environment == "local"
    else "INFO",  # minimum level (sets the threshold/floor value)
    filter=lambda record: record["level"].no <= logger.level("WARNING").no,
    # debug, info, warning logs
    rotation="10MB",
    retention="30 days",
    compression="zip",
)

# ERROR logger
logger.add(
    sink=os.path.join(LOG_DIR, "error.log"),
    format=LOG_FORMAT,
    level="ERROR",  # error, critical logs
    rotation="10MB",
    retention="30 days",
    compression="zip",
    backtrace=True,
    diagnose=True,
)


def get_logger():
    return logger
