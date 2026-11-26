"""Environment configuration for the AIRWISE AI backend."""

from functools import lru_cache
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    app_name: str = "AIRWISE AI API"
    app_version: str = "0.9.1"
    environment: str = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    default_location_id: str = "lagos-ng"

    # Open-Meteo Air Quality API settings
    open_meteo_base_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality"
    open_meteo_domains: str = "cams_global"
    open_meteo_timeout_seconds: float = 8.0
    open_meteo_cache_ttl_seconds: int = 300
    open_meteo_forecast_hours: int = 24

    # Historical Air Quality Engine settings (separate from live 300s cache)
    history_db_path: str = "data/airwise_history.db"
    history_cache_ttl_seconds: int = 1200
    history_refresh_max_age_seconds: int = 21600
    history_timeout_seconds: float = 12.0

    # Google Gemini API settings (backend-only; never exposed to frontend or logs)
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AIRWISE_GEMINI_API_KEY", "GEMINI_API_KEY"),
    )
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_seconds: float = 15.0

    model_config = SettingsConfigDict(
        env_prefix="AIRWISE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.startswith("/"):
            return f"/{cleaned}"
        return cleaned.rstrip("/")

    @field_validator("gemini_api_key")
    @classmethod
    def normalize_gemini_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated allowed origins into a clean list."""
        origins = [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]
        return origins or ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
