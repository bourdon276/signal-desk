from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
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
    steam_use_env_proxy: bool = False
    cninfo_access_token: SecretStr = SecretStr("")
    cninfo_display_allowed: bool = False
    cninfo_daily_request_limit: int = Field(default=24, ge=1, le=100)
    pandascore_token: SecretStr = SecretStr("")

    model_enabled: bool = False
    model_api_key: SecretStr = SecretStr("")
    model_base_url: str = ""
    model_name: str = ""
    model_input_cny_per_million: float = Field(default=0, ge=0, le=1000)
    model_output_cny_per_million: float = Field(default=0, ge=0, le=1000)
    model_month_budget_cny: float = Field(default=50, gt=0, le=100)
    model_day_budget_cny: float = Field(default=3, gt=0, le=10)
    model_request_budget_cny: float = Field(default=0.5, gt=0, le=1)

    @field_validator("model_base_url")
    @classmethod
    def model_endpoint(cls, value: str) -> str:
        if not value:
            return value
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError("model endpoint must be an HTTPS base URL without credentials or query")
        return value.rstrip("/")

    @field_validator("database_url")
    @classmethod
    def psycopg_url(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
