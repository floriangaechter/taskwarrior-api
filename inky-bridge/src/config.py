"""Configuration management for inky-bridge."""

import os
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import (
    DEFAULT_DATA_DIR,
    DEFAULT_MIN_SYNC_INTERVAL_SECONDS,
    DEFAULT_SYNC_TIMEOUT_SECONDS,
    SECRET_PATH,
)
from .exceptions import ConfigurationError


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

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
    TASKCHAMPION_ENCRYPTION_SECRET: Optional[str] = Field(
        default=None, description="Encryption secret (from Docker secret or env var)"
    )

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
        """Validate sync timeout is positive."""
        if v <= 0:
            raise ValueError("SYNC_TIMEOUT_SECONDS must be positive")
        return v

    @field_validator("MIN_SYNC_INTERVAL_SECONDS")
    @classmethod
    def validate_min_sync_interval(cls, v: int) -> int:
        """Validate min sync interval is non-negative."""
        if v < 0:
            raise ValueError("MIN_SYNC_INTERVAL_SECONDS must be non-negative")
        return v

    def model_post_init(self, __context) -> None:
        """Post-initialization: load encryption secret and ensure data directory exists."""
        # Load encryption secret from Docker secret file if not set via env var
        if not self.TASKCHAMPION_ENCRYPTION_SECRET:
            secret_path = Path(SECRET_PATH)
            if secret_path.exists():
                self.TASKCHAMPION_ENCRYPTION_SECRET = secret_path.read_text().strip()

        if not self.TASKCHAMPION_ENCRYPTION_SECRET:
            raise ConfigurationError(
                "TASKCHAMPION_ENCRYPTION_SECRET must be provided via Docker secret "
                "or environment variable"
            )

        # Ensure data directory exists
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)

    # Convenience properties for backward compatibility
    @property
    def sync_server_url(self) -> str:
        """Get sync server URL."""
        return self.TASKCHAMPION_SYNC_SERVER_URL

    @property
    def client_id(self) -> str:
        """Get client ID."""
        return self.TASKCHAMPION_CLIENT_ID

    @property
    def encryption_secret(self) -> str:
        """Get encryption secret."""
        if not self.TASKCHAMPION_ENCRYPTION_SECRET:
            raise ConfigurationError("Encryption secret not set")
        return self.TASKCHAMPION_ENCRYPTION_SECRET

    @property
    def data_dir(self) -> str:
        """Get data directory."""
        return self.DATA_DIR

    @property
    def sync_timeout_seconds(self) -> int:
        """Get sync timeout in seconds."""
        return self.SYNC_TIMEOUT_SECONDS

    @property
    def min_sync_interval_seconds(self) -> int:
        """Get minimum sync interval in seconds."""
        return self.MIN_SYNC_INTERVAL_SECONDS

    @property
    def auth_secret(self) -> str:
        """Get auth secret."""
        return self.AUTH_SECRET

    def requires_auth(self) -> bool:
        """Check if API authentication is required."""
        return bool(self.AUTH_SECRET)


# Global settings instance
_settings: Optional[Settings] = None


def get_config() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        try:
            _settings = Settings()
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {e}") from e
    return _settings
