"""Pydantic models for API responses."""

from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

TZ_ZURICH = ZoneInfo("Europe/Zurich")


class TaskTimestamps(BaseModel):
    entry: str
    modified: str
    scheduled: Optional[str] = None
    start: Optional[str] = None  # set when task is active (task start)
    wait: Optional[str] = None


class Task(BaseModel):
    uuid: str
    short_id: str
    description: str
    status: str
    project: Optional[str] = None
    active: bool = False  # True when task has been started (task start) and not yet completed
    timestamps: TaskTimestamps


class SyncMeta(BaseModel):
    sync_ok: bool
    stale: bool
    last_sync_at: Optional[str] = None
    duration_ms: int


class OverviewResponse(BaseModel):
    meta: SyncMeta
    tasks: List[Task]


class HealthResponse(BaseModel):
    status: str
    last_sync_at: Optional[str] = None
    replica_path: str


def format_timestamp(dt: Optional[datetime]) -> Optional[str]:
    """UTC datetime → ISO 8601 string in Europe/Zurich."""
    if dt is None:
        return None

    # Convert UTC to Europe/Zurich
    zurich_dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ_ZURICH)
    return zurich_dt.isoformat()
