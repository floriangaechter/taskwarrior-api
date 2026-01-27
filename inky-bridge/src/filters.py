"""Task filtering and sorting logic."""

import taskchampion
from datetime import datetime
from typing import List

from .constants import (
    STATUS_COMPLETED,
    STATUS_DELETED,
    STATUS_PENDING,
    STATUS_RECURRING,
    STATUS_UNKNOWN,
    TAG_SOMEDAY,
)
from .models import Task, TaskTimestamps, format_timestamp


def _map_status(status_obj: taskchampion.Status) -> str:
    """
    Map TaskChampion Status enum to string.

    Args:
        status_obj: TaskChampion Status enum value

    Returns:
        Lowercase status string
    """
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
    """
    Parse scheduled timestamp string to datetime.

    Args:
        scheduled_str: ISO 8601 timestamp string

    Returns:
        Datetime object or None if parsing fails
    """
    if not scheduled_str:
        return None

    try:
        # Try parsing ISO 8601 format
        return datetime.fromisoformat(scheduled_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def normalize_task(task: taskchampion.Task) -> Task:
    """
    Convert TaskChampion Task to normalized Task model.

    Args:
        task: TaskChampion Task object

    Returns:
        Normalized Task model
    """
    uuid_str = str(task.get_uuid())
    short_id = uuid_str[:8]

    # Get task properties
    description = task.get_description() or ""
    status = _map_status(task.get_status())

    # Get tags - get_tags() returns list of Tag objects
    tags = sorted(str(tag) for tag in task.get_tags())
    tags_sort_key = ",".join(tags)

    # Get timestamps
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
        tags=tags,
        tags_sort_key=tags_sort_key,
        timestamps=timestamps,
    )


def apply_overview_filter(tasks: List[Task]) -> List[Task]:
    """
    Apply overview report filter: status==pending, exclude someday tag.

    Args:
        tasks: List of normalized tasks

    Returns:
        Filtered list of tasks matching overview criteria
    """
    return [
        task
        for task in tasks
        if task.status == STATUS_PENDING and TAG_SOMEDAY not in task.tags
    ]


def apply_overview_sort(tasks: List[Task]) -> List[Task]:
    """
    Apply overview report sort: tags_sort_key ascending, then entry timestamp ascending.

    Args:
        tasks: List of normalized tasks

    Returns:
        Sorted list of tasks
    """
    return sorted(
        tasks,
        key=lambda t: (
            t.tags_sort_key,
            t.timestamps.entry,
        ),
    )


