"""Replica management: sync + read tasks, all in one thread to avoid conflicts."""

import logging
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import taskchampion

from .config import get_config

logger = logging.getLogger(__name__)

SYNC_TIMEOUT_SECONDS = 30
MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class TaskData:
    """Raw task data extracted from TaskChampion (thread-safe, plain Python)."""
    uuid: str
    status: str
    description: str
    project: Optional[str]
    is_active: bool
    entry: Optional[datetime]
    modified: Optional[datetime]
    scheduled: Optional[str]
    start: Optional[str]
    wait: Optional[datetime]


@dataclass
class SyncResult:
    """Result of a sync + read operation."""
    success: bool
    tasks: List[TaskData]
    error: Optional[str] = None


class ReplicaWorker:
    """
    Manages all Replica operations in a dedicated thread.
    
    TaskChampion's Replica is not thread-safe, so we do ALL operations
    (create, sync, read) in a single dedicated thread.
    """
    
    def __init__(self, data_dir: str, sync_url: str, client_id: str, encryption_secret: str):
        self.data_dir = data_dir
        self.sync_url = sync_url
        self.client_id = client_id.lower()  # UUIDs should be lowercase
        self.encryption_secret = encryption_secret
        
        self._lock = threading.Lock()
        self._replica: Optional[taskchampion.Replica] = None
        self._last_sync: Optional[datetime] = None
        self._consecutive_failures = 0
        self._cached_tasks: List[TaskData] = []
    
    def _ensure_data_dir(self) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
    
    def _reset_replica(self) -> None:
        """Clear replica directory to start fresh."""
        self._replica = None
        path = Path(self.data_dir)
        if path.exists():
            try:
                shutil.rmtree(path)
                logger.info(f"Cleared replica directory: {self.data_dir}")
            except Exception as e:
                logger.error(f"Failed to clear replica dir: {e}")
        self._ensure_data_dir()
    
    def _get_or_create_replica(self) -> taskchampion.Replica:
        """Get existing replica or create new one."""
        if self._replica is None:
            self._ensure_data_dir()
            logger.info(f"Creating replica at {self.data_dir}")
            self._replica = taskchampion.Replica.new_on_disk(self.data_dir, True)
        return self._replica
    
    def _extract_task_data(self, task: taskchampion.Task) -> TaskData:
        """Extract plain Python data from TaskChampion Task object."""
        status_obj = task.get_status()
        
        # Map status using equality checks (Status enum isn't hashable)
        if status_obj == taskchampion.Status.Pending:
            status = "pending"
        elif status_obj == taskchampion.Status.Completed:
            status = "completed"
        elif status_obj == taskchampion.Status.Deleted:
            status = "deleted"
        elif status_obj == taskchampion.Status.Recurring:
            status = "recurring"
        else:
            status = "unknown"
        
        return TaskData(
            uuid=str(task.get_uuid()),
            status=status,
            description=task.get_description() or "",
            project=task.get_value("project"),
            is_active=task.is_active(),
            entry=task.get_entry(),
            modified=task.get_modified(),
            scheduled=task.get_value("scheduled"),
            start=task.get_value("start"),
            wait=task.get_wait(),
        )
    
    def _read_all_tasks(self) -> List[TaskData]:
        """Read all tasks from replica. Must be called with lock held."""
        replica = self._get_or_create_replica()
        tasks_dict = replica.all_tasks()
        return [self._extract_task_data(t) for t in tasks_dict.values()]
    
    def sync_and_read(self) -> SyncResult:
        """
        Sync with server and read all tasks.
        
        All operations happen under a lock to ensure only one thread
        accesses the Replica at a time.
        """
        with self._lock:
            # Check if we need to reset due to repeated failures
            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    f"Resetting replica after {self._consecutive_failures} consecutive failures"
                )
                self._reset_replica()
                self._consecutive_failures = 0
            
            # Try to sync
            try:
                replica = self._get_or_create_replica()
                
                logger.info(
                    f"Syncing with {self.sync_url} (client_id={self.client_id})"
                )
                start = time.time()
                
                replica.sync_to_remote(
                    self.sync_url,
                    self.client_id,
                    self.encryption_secret,
                    False,  # avoid_snapshots
                )
                
                elapsed_ms = int((time.time() - start) * 1000)
                logger.info(f"Sync succeeded in {elapsed_ms}ms")
                
                self._last_sync = datetime.utcnow()
                self._consecutive_failures = 0
                
                # Read tasks after successful sync
                tasks = self._read_all_tasks()
                self._cached_tasks = tasks
                
                return SyncResult(success=True, tasks=tasks)
                
            except Exception as e:
                self._consecutive_failures += 1
                error_msg = str(e)
                logger.error(
                    f"Sync failed (attempt {self._consecutive_failures}): {error_msg}"
                )
                
                # On failure, try to return cached/existing tasks
                try:
                    if not self._cached_tasks:
                        self._cached_tasks = self._read_all_tasks()
                    return SyncResult(
                        success=False,
                        tasks=self._cached_tasks,
                        error=error_msg,
                    )
                except Exception as read_error:
                    logger.error(f"Failed to read tasks: {read_error}")
                    return SyncResult(
                        success=False,
                        tasks=[],
                        error=f"Sync: {error_msg}, Read: {read_error}",
                    )
    
    def read_only(self) -> List[TaskData]:
        """Read tasks without syncing (for health checks, etc.)."""
        with self._lock:
            try:
                return self._read_all_tasks()
            except Exception as e:
                logger.error(f"Failed to read tasks: {e}")
                return self._cached_tasks
    
    @property
    def last_sync_time(self) -> Optional[datetime]:
        return self._last_sync


# Global worker instance
_worker: Optional[ReplicaWorker] = None
_worker_lock = threading.Lock()


def get_replica_worker() -> ReplicaWorker:
    """Get or create the global ReplicaWorker instance."""
    global _worker
    if _worker is None:
        with _worker_lock:
            if _worker is None:
                config = get_config()
                _worker = ReplicaWorker(
                    data_dir=config.data_dir,
                    sync_url=config.sync_server_url,
                    client_id=config.client_id,
                    encryption_secret=config.encryption_secret,
                )
    return _worker
