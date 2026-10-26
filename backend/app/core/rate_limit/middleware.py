import math
import time
from datetime import datetime, timedelta, timezone
from typing import Tuple

import jwt
from fastapi import Request, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from backend.app.core.config import settings
from backend.app.core.db import engine
from backend.app.core.logging import get_logger
from backend.app.core.rate_limit.config import (
    DEFAULT_RATE_LIMITS,
    RATE_LIMIT_WHITELIST,
    RateLimitConfig,
)
from backend.app.core.rate_limit.models import RateLimitLog

logger = get_logger()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

        # ponytail: no startup ping (async client can't be awaited here); a down Redis fails open per request
        self.redis_client = Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True,
        )

    async def _get_rate_limit_key(self, request: Request, endpoint: str) -> str:
        ip = request.client.host if request.client else "anonymous"

        try:
            access_token = request.cookies.get(settings.COOKIE_ACCESS_NAME)
            user_id = (
                jwt.decode(
                    access_token, settings.SIGNING_KEY, algorithms=["HS256"]
                ).get("user_id")
                if access_token
                else None
            )
            if user_id is None:
                key = f"ratelimit:{endpoint}:{ip}"
            else:
                key = f"ratelimit:{endpoint}:{ip}:{user_id}"
        except Exception:
            key = f"ratelimit:{endpoint}:{ip}"

        return key

    async def _get_limit_config(self, endpoint: str) -> RateLimitConfig:
        return DEFAULT_RATE_LIMITS.get(endpoint, DEFAULT_RATE_LIMITS["default"])

    async def _check_rate_limit(
        self, key: str, config: RateLimitConfig
    ) -> Tuple[
        # isRateLimited, currentCount, blockUntil
        bool, int | None, datetime | None
    ]:
        try:
            async with self.redis_client.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.ttl(key)
                count, ttl = await pipe.execute()

            # New key (or one that lost its expiry)
            if ttl < 0:
                await self.redis_client.expire(key, config.time_window)
                ttl = config.time_window

            if count > config.max_requests:
                if config.block_on_exceed:
                    return (
                        True,
                        count,
                        datetime.now(timezone.utc) + timedelta(seconds=ttl),
                    )
                return True, count, None

            return False, count, None

        except Exception as e:
            logger.exception(f"Rate limit check failed: {e}")
            return False, None, None

    async def _log_violation(
        self,
        request: Request,
        endpoint: str,
        count: int,
        blocked_until: datetime | None,
        session: AsyncSession,
    ) -> None:
        try:
            user_id = None
            access_token = request.cookies.get(settings.COOKIE_ACCESS_NAME)
            if access_token:
                try:
                    user_id = jwt.decode(
                        access_token,
                        settings.SIGNING_KEY,
                        algorithms=[settings.JWT_ALGORITHM],
                    ).get("id")

                except jwt.InvalidTokenError:
                    pass

            window_start = datetime.now(timezone.utc)
            window_end = (
                blocked_until if blocked_until else window_start + timedelta(hours=1)
            )

            violation_log = RateLimitLog(
                ip_address=request.client.host if request.client else "unknown",
                user_id=user_id,
                endpoint=endpoint,
                request_count=count,
                request_method=str(request.method),
                request_path=str(request.url.path),
                window_start=window_start,
                window_end=window_end,
                blocked_until=blocked_until,
            )

            session.add(violation_log)
            await session.commit()
            await session.refresh(violation_log)

            logger.info(
                f"Rate limit violation loggeg for the IP: {violation_log.ip_address}, "
                f"User ID: {violation_log.user_id}, Endpoint: {violation_log.endpoint}"
            )

        except Exception as e:
            logger.error(f"Failed to log rate limit violation: {str(e)}")
            await session.rollback()
            raise

    async def dispatch(self, request: Request, call_next):
        try:
            endpoint = request.url.path
            if endpoint in RATE_LIMIT_WHITELIST:
                response = await call_next(request)
                response.headers["X-RateLimit-Limit"] = "unlimited"
                response.headers["X-RateLimit-Remaining"] = "unlimited"
                return response

            config = await self._get_limit_config(endpoint)
            key = await self._get_rate_limit_key(request, endpoint)

            (
                is_rate_limited,
                current_count,
                blocked_until,
            ) = await self._check_rate_limit(key, config)

            headers = {
                "X-RateLimit-Limit": str(config.max_requests),
                "X-RateLimit-Remaining": str(
                    max(0, config.max_requests - (current_count or 0))
                ),
                "X-RateLimit-Reset": str(int(time.time() + config.time_window)),
            }

            if is_rate_limited:
                async with AsyncSession(engine) as session:
                    await self._log_violation(
                        request, endpoint, current_count or 0, blocked_until, session
                    )

                retry_after = (
                    max(
                        1,
                        math.ceil(
                            (blocked_until - datetime.now(timezone.utc)).total_seconds()
                        ),
                    )
                    if blocked_until
                    else config.time_window
                )

                response = JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "status": "error",
                        "message": "Too many requests",
                        "action": "Please wait before trying again",
                        "retry_after": f"{retry_after} seconds",
                    },
                )

                for header_key, header_value in headers.items():
                    response.headers[header_key] = header_value

                if blocked_until:
                    response.headers["Retry-After"] = str(retry_after)

                return response

            response = await call_next(request)

            for header_key, header_value in headers.items():
                response.headers[header_key] = header_value

            return response

        except Exception as e:
            logger.error(f"Failed to dispatch: {str(e)}")
            return await call_next(request)
