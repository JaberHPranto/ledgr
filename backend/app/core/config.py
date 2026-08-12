from typing import Literal

import cloudinary
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../../.envs/.env.local", env_ignore_empty=True, extra="ignore"
    )
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    API_V1: str = ""
    PROJECT_NAME: str = ""
    PROJECT_DESCRIPTION: str = ""
    SITE_NAME: str = ""
    DB_URL: str = ""

    MAIL_FROM: str = ""
    MAIL_FROM_NAME: str = ""
    SMTP_HOST: str = "mailpit"
    SMTP_PORT: int = 1025
    MAILPIT_UI_PORT: int = 8025

    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    RABBITMQ_HOST: str = "rabbitmq"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str = "guest"
    RABBITMQ_PASSWORD: str = "guest"

    OTP_EXPIRATION_MINUTES: int = 2 if ENVIRONMENT == "local" else 5
    LOGIN_ATTEMPTS_LIMIT: int = 3
    LOCKOUT_DURATION_MINUTES: int = 2 if ENVIRONMENT == "local" else 5
    ACTIVATION_TOKEN_EXPIRATION_MINUTES: int = 2 if ENVIRONMENT == "local" else 5
    API_BASE_URL: str = ""
    SUPPORT_EMAIL: str = ""

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRATION_MINUTES: int = 30 if ENVIRONMENT == "local" else 15
    JWT_REFRESH_TOKEN_EXPIRATION_DAYS: int = 1

    COOKIE_SECURE: bool = False if ENVIRONMENT == "local" else True
    COOKIE_ACCESS_NAME: str = "access_token"
    COOKIE_REFRESH_NAME: str = "refresh_token"
    COOKIE_LOGGED_IN_NAME: str = "logged_in"
    COOKIE_HTTP_ONLY: bool = True
    COOKIE_SAMESITE: str = "lax"
    COOKIE_PATH: str = "/"
    SIGNING_KEY: str = ""

    PASSWORD_RESET_TOKEN_EXPIRATION_MINUTES: int = 3 if ENVIRONMENT == "local" else 5

    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    ALLOWED_MIME_TYPES: list[str] = ["image/png", "image/jpeg", "image/jpg"]
    MAX_FILE_SIZE: int = 5 * 1024 * 1024  # 5 MB
    MAX_DIMENSIONS: int = 4096


settings = Settings()

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
)
