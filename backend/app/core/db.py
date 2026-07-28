from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession

from backend.app.core.config import settings
from backend.app.core.logging import get_logger

logger = get_logger()

engine = create_async_engine(settings.DB_URL)

async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        except Exception as e:
            logger.exception(f"An error occurred while getting async session: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    pass
