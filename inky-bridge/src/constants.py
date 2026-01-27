"""Application constants."""

# Task status values
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_DELETED = "deleted"
STATUS_RECURRING = "recurring"
STATUS_UNKNOWN = "unknown"

# Tag filters
TAG_SOMEDAY = "someday"

# Default configuration values
DEFAULT_DATA_DIR = "/data/replica"
DEFAULT_SYNC_TIMEOUT_SECONDS = 30
DEFAULT_MIN_SYNC_INTERVAL_SECONDS = 10

# Docker secret path
SECRET_PATH = "/run/secrets/taskchampion_encryption_secret"
