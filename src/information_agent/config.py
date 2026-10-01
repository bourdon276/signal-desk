from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    database_url: str = "sqlite:///./data/information.db"
    timezone: str = "Asia/Shanghai"
    app_secret: str = "local-development-only-change-me"
    admin_token: str = ""
    registration_code: str = ""
    cors_origins: str = "http://localhost:5173"
    sync_in_web: bool = False

    @field_validator("database_url")
    @classmethod
    def psycopg_url(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
