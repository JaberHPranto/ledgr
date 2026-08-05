import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette import status

from backend.app.api.main import api_router
from backend.app.core.config import settings
from backend.app.core.db import engine, init_db
from backend.app.core.health import ServiceStatus, health_checker
from backend.app.core.logging import get_logger

logger = get_logger()


async def startup_health_check(timeout: float = 90.0):
    try:
        async with asyncio.timeout(timeout):
            start_time = time.time()
            retry_intervals = [1, 2, 5, 10, 15]

            while True:
                is_healthy = await health_checker.wait_for_services()
                if is_healthy:
                    return True

                elapsed_time = time.time() - start_time
                if elapsed_time > timeout:
                    logger.error(f"Health check timed out after {timeout} seconds")
                    return False

                wait_time = retry_intervals[
                    min(int(elapsed_time / 10), len(retry_intervals) - 1)
                ]
                logger.info(f"Waiting {wait_time} seconds before retrying health check")
                await asyncio.sleep(wait_time)

    except asyncio.TimeoutError:
        logger.error(f"Health check timed out after {timeout} seconds")
        return False
    except Exception as e:
        logger.error(f"Error during startup health check: {e}")
        return False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await init_db()

        await health_checker.add_service(
            "database", check_function=health_checker.check_database
        )
        await health_checker.add_service(
            "celery", check_function=health_checker.check_celery
        )
        await health_checker.add_service(
            "redis", check_function=health_checker.check_redis
        )

        if not await startup_health_check():
            raise RuntimeError("Health check failed during startup")

        logger.info("All services initialized and healthy")
        yield
    except Exception as e:
        logger.error(f"Error during startup: {e}")
        await engine.dispose()
        await health_checker.cleanup()
        raise
    finally:
        logger.info("Shutting down")
        await engine.dispose()
        await health_checker.cleanup()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    docs_url=f"{settings.API_V1}/docs",
    redoc_url=f"{settings.API_V1}/redoc",
    openapi_url=f"{settings.API_V1}/openapi.json",
    lifespan=lifespan,
)


@app.get("/health", response_model=dict)
async def health_check():
    try:
        health_status = await health_checker.check_all_services()

        if health_status["status"] == ServiceStatus.HEALTHY:
            status_code = status.HTTP_200_OK
        elif health_status["status"] == ServiceStatus.DEGRADED:
            status_code = status.HTTP_206_PARTIAL_CONTENT
        else:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return JSONResponse(status_code=status_code, content=health_status)

    except Exception as e:
        logger.error(f"Error during health check: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": "error", "details": str(e)},
        )


app.include_router(api_router, prefix=settings.API_V1)
