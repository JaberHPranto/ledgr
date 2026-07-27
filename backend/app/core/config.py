from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../../.envs/.env.local", env_ignore_empty=True, extra="ignore"
    )
    Environment: Literal["local", "staging", "production"] = "local"
    API_V1: str = ""
    PROJECT_NAME: str = ""
    PROJECT_DESCRIPTION: str = ""
    SITE_NAME: str = ""
    DB_URL: str = ""


settings = Settings()
