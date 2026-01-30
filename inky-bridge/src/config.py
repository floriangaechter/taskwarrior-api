"""Config from env (pydantic-settings)."""

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import (
    DEFAULT_DATA_DIR,
    DEFAULT_MIN_SYNC_INTERVAL_SECONDS,
    DEFAULT_SYNC_TIMEOUT_SECONDS,
)
from .exceptions import ConfigurationError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,  # Don't load from .env file
        case_sensitive=True,
        extra="ignore",
    )

    # Required configuration (environment variable names match field names)
    TASKCHAMPION_SYNC_SERVER_URL: str = Field(
        ..., description="URL of the TaskChampion sync server"
    )
    TASKCHAMPION_CLIENT_ID: str = Field(..., description="Client ID for the bridge replica")
    TASKCHAMPION_ENCRYPTION_SECRET: str = Field(
        ..., description="Encryption secret (same as Taskwarrior sync.encryption_secret)"
    )

    @model_validator(mode="after")
    def check_encryption_secret(self) -> "Settings":
        secret = (self.TASKCHAMPION_ENCRYPTION_SECRET or "").strip()
        if not secret:
            raise ValueError(
                "TASKCHAMPION_ENCRYPTION_SECRET is empty or missing. "
                "Set it in .env next to docker-compose.yml and run 'docker compose up' from that directory. "
                "Check with: docker compose run --rm inky-bridge env | grep TASKCHAMPION"
            )
        return self

    # Optional configuration with defaults
    DATA_DIR: str = Field(default=DEFAULT_DATA_DIR, description="Replica storage directory")
    SYNC_TIMEOUT_SECONDS: int = Field(
        default=DEFAULT_SYNC_TIMEOUT_SECONDS, description="Sync timeout in seconds"
    )
    MIN_SYNC_INTERVAL_SECONDS: int = Field(
        default=DEFAULT_MIN_SYNC_INTERVAL_SECONDS,
        description="Minimum sync interval in seconds",
    )
    AUTH_SECRET: str = Field(default="", description="API authentication secret")

    @field_validator("SYNC_TIMEOUT_SECONDS")
    @classmethod
    def validate_sync_timeout(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("SYNC_TIMEOUT_SECONDS must be positive")
        return v

    @field_validator("MIN_SYNC_INTERVAL_SECONDS")
    @classmethod
    def validate_min_sync_interval(cls, v: int) -> int:
        if v < 0:
            raise ValueError("MIN_SYNC_INTERVAL_SECONDS must be non-negative")
        return v

    def model_post_init(self, __context) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)

    @property
    def sync_server_url(self) -> str:
        return self.TASKCHAMPION_SYNC_SERVER_URL

    @property
    def client_id(self) -> str:
        return self.TASKCHAMPION_CLIENT_ID

    @property
    def encryption_secret(self) -> str:
        secret = (self.TASKCHAMPION_ENCRYPTION_SECRET or "").strip()
        if not secret:
            raise ConfigurationError(
                "TASKCHAMPION_ENCRYPTION_SECRET is empty or missing. "
                "Set it in .env and ensure the container receives it (e.g. run from the project dir: docker compose up)."
            )
        return secret

    @property
    def data_dir(self) -> str:
        return self.DATA_DIR

    @property
    def sync_timeout_seconds(self) -> int:
        return self.SYNC_TIMEOUT_SECONDS

    @property
    def min_sync_interval_seconds(self) -> int:
        return self.MIN_SYNC_INTERVAL_SECONDS

    @property
    def auth_secret(self) -> str:
        return self.AUTH_SECRET

    def requires_auth(self) -> bool:
        return bool(self.AUTH_SECRET)


# Global settings instance
_settings: Optional[Settings] = None


def get_config() -> Settings:
    global _settings
    if _settings is None:
        try:
            _settings = Settings()
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {e}") from e
    return _settings
