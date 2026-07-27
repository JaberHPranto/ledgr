from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.main import api_router
from .core.config import settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from .core.db import init_db

    await init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    docs_url=f"{settings.API_V1}/docs",
    redoc_url=f"{settings.API_V1}/redoc",
    openapi_url=f"{settings.API_V1}/openapi.json",
    lifespan=lifespan,
)

app.include_router(api_router, prefix=settings.API_V1)
