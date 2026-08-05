import asyncio
from typing import AsyncGenerator

from sqlalchemy import AsyncAdaptedQueuePool, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.core.model_registry import load_models

logger = get_logger()

engine = create_async_engine(
    settings.DB_URL,
    poolclass=AsyncAdaptedQueuePool,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,  # recycle connections after 30 minutes
)

async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    session = async_session()
    try:
        yield session
    except Exception as e:
        logger.error(f"An error occurred while getting async session: {e}")
        if session:
            try:
                await session.rollback()
            except Exception as rollback_error:
                logger.error(f"Failed to rollback session: {rollback_error}")
        raise
    finally:
        if session:
            try:
                await session.close()
            except Exception as close_error:
                logger.error(f"Failed to close session: {close_error}")


async def init_db() -> None:
    try:
        load_models()
        logger.info("Models loaded successfully")

        max_retries = 3
        retry_delay = 2  # seconds
        for attempt in range(max_retries):
            try:
                async with engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                logger.info("Database initialized successfully")
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error("Failed to initialize database")
                    raise

                logger.warning(
                    f"Failed to initialize database (attempt {attempt + 1}/{max_retries}): {e}"
                )
                await asyncio.sleep(retry_delay * (attempt + 1))
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
