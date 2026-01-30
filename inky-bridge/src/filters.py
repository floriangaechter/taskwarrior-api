"""Convert TaskData to Task model, filter (pending only), sort (project, entry)."""

from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from .models import Task, TaskTimestamps, format_timestamp
from .replica import TaskData


def _parse_timestamp_string(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse timestamp string (epoch or ISO) to datetime."""
    if not ts_str:
        return None
    
    # Try epoch first (Taskwarrior stores as decimal)
    try:
        epoch = float(ts_str)
        return datetime.fromtimestamp(epoch, tz=ZoneInfo("UTC"))
    except (ValueError, TypeError, OSError):
        pass
    
    # Try ISO format
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def task_data_to_model(td: TaskData) -> Task:
    """Convert TaskData (from replica) to Task model (for API response)."""
    
    # Parse string timestamps
    scheduled_dt = _parse_timestamp_string(td.scheduled)
    start_dt = _parse_timestamp_string(td.start)
    
    timestamps = TaskTimestamps(
        entry=format_timestamp(td.entry) or "",
        modified=format_timestamp(td.modified) or "",
        scheduled=format_timestamp(scheduled_dt),
        start=format_timestamp(start_dt),
        wait=format_timestamp(td.wait),
    )
    
    return Task(
        uuid=td.uuid,
        short_id=td.uuid[:8],
        description=td.description,
        status=td.status,
        project=td.project,
        active=td.is_active,
        timestamps=timestamps,
    )


def filter_and_sort_overview(tasks: List[Task]) -> List[Task]:
    """Filter to pending only, sort by project then entry."""
    pending = [t for t in tasks if t.status == "pending"]
    return sorted(pending, key=lambda t: (t.project or "", t.timestamps.entry))
