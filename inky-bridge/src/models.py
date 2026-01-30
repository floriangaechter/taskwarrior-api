"""Pydantic models for API responses."""

from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field


# Europe/Zurich timezone
TZ_ZURICH = ZoneInfo("Europe/Zurich")


class TaskTimestamps(BaseModel):
    """Task timestamp fields."""

    entry: str = Field(..., description="Task entry timestamp (ISO 8601, Europe/Zurich)")
    modified: str = Field(..., description="Task modification timestamp (ISO 8601, Europe/Zurich)")
    scheduled: Optional[str] = Field(
        None, description="Scheduled timestamp (ISO 8601, Europe/Zurich) or null"
    )
    wait: Optional[str] = Field(
        None, description="Wait timestamp (ISO 8601, Europe/Zurich) or null"
    )


class Task(BaseModel):
    """Normalized task object."""

    uuid: str = Field(..., description="Task UUID (primary identifier)")
    short_id: str = Field(..., description="First 8 characters of UUID for display")
    description: str = Field(..., description="Task description")
    status: str = Field(..., description="Task status (e.g., pending, completed)")
    project: Optional[str] = Field(None, description="Task project (area/responsibility)")
    tags: List[str] = Field(..., description="List of task tags")
    tags_sort_key: str = Field(..., description="Deterministic sort key: comma-joined sorted tags")
    timestamps: TaskTimestamps = Field(..., description="Task timestamps")


class SyncMeta(BaseModel):
    """Metadata about sync operation."""

    sync_ok: bool = Field(..., description="Whether sync completed successfully")
    stale: bool = Field(..., description="Whether returned data is stale (sync failed/timed out)")
    last_sync_at: Optional[str] = Field(
        None, description="Last successful sync timestamp (ISO 8601, Europe/Zurich) or null"
    )
    duration_ms: int = Field(..., description="Sync operation duration in milliseconds")


class OverviewResponse(BaseModel):
    """Response for /overview endpoint."""

    meta: SyncMeta = Field(..., description="Sync metadata")
    tasks: List[Task] = Field(..., description="Filtered and sorted tasks matching overview criteria")


class TasksResponse(BaseModel):
    """Response for /tasks endpoint."""

    meta: SyncMeta = Field(..., description="Sync metadata")
    tasks: List[Task] = Field(..., description="All tasks (optionally filtered)")


class HealthResponse(BaseModel):
    """Response for /health endpoint."""

    status: str = Field(..., description="Service status")
    last_sync_at: Optional[str] = Field(
        None, description="Last successful sync timestamp (ISO 8601, Europe/Zurich) or null"
    )
    replica_path: str = Field(..., description="Path to replica storage directory")


def format_timestamp(dt: Optional[datetime]) -> Optional[str]:
    """
    Convert datetime to ISO 8601 string with Europe/Zurich timezone.

    Args:
        dt: Datetime object (assumed UTC) or None

    Returns:
        ISO 8601 formatted string with timezone offset, or None
    """
    if dt is None:
        return None

    # Convert UTC to Europe/Zurich
    zurich_dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ_ZURICH)
    return zurich_dt.isoformat()
