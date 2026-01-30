"""Overview filter (pending only) and sort (project, entry)."""

import taskchampion
from datetime import datetime
from typing import List

from .constants import (
    STATUS_COMPLETED,
    STATUS_DELETED,
    STATUS_PENDING,
    STATUS_RECURRING,
    STATUS_UNKNOWN,
)
from .models import Task, TaskTimestamps, format_timestamp


def _map_status(status_obj: taskchampion.Status) -> str:
    if status_obj == taskchampion.Status.Pending:
        return STATUS_PENDING
    elif status_obj == taskchampion.Status.Completed:
        return STATUS_COMPLETED
    elif status_obj == taskchampion.Status.Deleted:
        return STATUS_DELETED
    elif status_obj == taskchampion.Status.Recurring:
        return STATUS_RECURRING
    elif status_obj == taskchampion.Status.Unknown:
        return STATUS_UNKNOWN
    else:
        # Fallback: try string conversion
        status_str = str(status_obj)
        if "." in status_str:
            return status_str.split(".")[-1].lower()
        return status_str.lower() if status_str else STATUS_PENDING


def _parse_scheduled_timestamp(scheduled_str: str) -> datetime | None:
    if not scheduled_str:
        return None

    try:
        # Try parsing ISO 8601 format
        return datetime.fromisoformat(scheduled_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def normalize_task(task: taskchampion.Task) -> Task:
    """TaskChampion Task → our Task model (UUID, description, status, timestamps, project)."""
    uuid_str = str(task.get_uuid())
    short_id = uuid_str[:8]

    description = task.get_description() or ""
    status = _map_status(task.get_status())
    project = task.get_value("project") or None

    entry_ts = task.get_entry()
    modified_ts = task.get_modified()
    scheduled_ts_str = task.get_value("scheduled")
    scheduled_ts = _parse_scheduled_timestamp(scheduled_ts_str) if scheduled_ts_str else None
    wait_ts = task.get_wait()

    timestamps = TaskTimestamps(
        entry=format_timestamp(entry_ts) or "",
        modified=format_timestamp(modified_ts) or "",
        scheduled=format_timestamp(scheduled_ts),
        wait=format_timestamp(wait_ts),
    )

    return Task(
        uuid=uuid_str,
        short_id=short_id,
        description=description,
        status=status,
        project=project,
        timestamps=timestamps,
    )


def apply_overview_filter(tasks: List[Task]) -> List[Task]:
    """Pending only."""
    return [task for task in tasks if task.status == STATUS_PENDING]


def apply_overview_sort(tasks: List[Task]) -> List[Task]:
    """Sort by project, then entry (report.overview.sort=project+,entry+)."""
    return sorted(
        tasks,
        key=lambda t: (
            t.project or "",
            t.timestamps.entry,
        ),
    )


