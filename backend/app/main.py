from .api.main import api_router
from fastapi import FastAPI

from .core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    docs_url=f"{settings.API_V1}/docs",
    redoc_url=f"{settings.API_V1}/redoc",
    openapi_url=f"{settings.API_V1}/openapi.json",
)

app.include_router(api_router, prefix=settings.API_V1)
