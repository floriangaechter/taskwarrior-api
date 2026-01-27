"""Replica management and sync logic."""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

import taskchampion

from .config import get_config
from .exceptions import ReplicaError, SyncError

logger = logging.getLogger(__name__)


class ReplicaManager:
    """Manages TaskChampion replica and synchronization."""

    def __init__(self):
        self.config = get_config()
        self._replica: Optional[taskchampion.Replica] = None
        self._replica_lock = asyncio.Lock()  # Lock for replica access
        self._sync_lock = asyncio.Lock()
        self._last_sync_time: Optional[float] = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sync")
        self._last_sync_success: Optional[datetime] = None

    def _get_replica(self) -> taskchampion.Replica:
        """
        Get or create the replica instance.
        
        IMPORTANT: Replica objects are NOT thread-safe and must be accessed
        from the same thread. This method should only be called from the
        main event loop thread, not from thread pool executors.
        """
        if self._replica is None:
            logger.info(f"Initializing replica at {self.config.data_dir}")
            self._replica = taskchampion.Replica.new_on_disk(
                self.config.data_dir, True
            )
        return self._replica

    def _sync_blocking(
        self, data_dir: str, sync_server_url: str, client_id: str, encryption_secret: str
    ) -> bool:
        """
        Perform sync operation (blocking, runs in thread pool).

        Creates a new Replica instance in this thread since Replica is not
        thread-safe and cannot be shared across threads.

        Args:
            data_dir: Path to replica data directory
            sync_server_url: URL of sync server
            client_id: Client ID for sync
            encryption_secret: Encryption secret

        Returns:
            True if sync succeeded, False otherwise

        Raises:
            SyncError: If sync fails with a non-recoverable error
        """
        try:
            # Create replica in this thread (thread pool thread)
            logger.info(f"Creating replica in sync thread at {data_dir}")
            replica = taskchampion.Replica.new_on_disk(data_dir, True)
            logger.info(f"Starting sync with server at {sync_server_url}")
            replica.sync_to_remote(
                sync_server_url,
                client_id,
                encryption_secret,
                False,  # avoid_snapshots = False
            )
            logger.info("Sync completed successfully")
            return True
        except Exception as e:
            logger.error(f"Sync failed: {e}", exc_info=True)
            # Don't raise - return False to allow stale data fallback
            return False

    async def sync_with_timeout(self) -> bool:
        """
        Perform sync with timeout and single-flight lock.

        Returns:
            True if sync succeeded, False otherwise
        """
        # Check min sync interval
        now = time.time()
        if (
            self._last_sync_time is not None
            and (now - self._last_sync_time) < self.config.min_sync_interval_seconds
        ):
            logger.debug(
                f"Skipping sync: min interval not met "
                f"({now - self._last_sync_time:.1f}s < {self.config.min_sync_interval_seconds}s)"
            )
            return self._last_sync_success is not None

        # Acquire lock (single-flight)
        async with self._sync_lock:
            # Double-check min interval after acquiring lock
            now = time.time()
            if (
                self._last_sync_time is not None
                and (now - self._last_sync_time) < self.config.min_sync_interval_seconds
            ):
                logger.debug("Skipping sync: another request already synced")
                return self._last_sync_success is not None

            self._last_sync_time = now
            start_time = time.time()

            try:
                # Run sync in thread pool with timeout
                # Pass config values as arguments since Replica can't be shared across threads
                success = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        self._executor,
                        self._sync_blocking,
                        self.config.data_dir,
                        self.config.sync_server_url,
                        self.config.client_id,
                        self.config.encryption_secret,
                    ),
                    timeout=self.config.sync_timeout_seconds,
                )
                duration_ms = int((time.time() - start_time) * 1000)
                if success:
                    logger.info(f"Sync succeeded in {duration_ms}ms")
                    self._last_sync_success = datetime.utcnow()
                else:
                    logger.warning(f"Sync failed after {duration_ms}ms")
                return success
            except asyncio.TimeoutError:
                duration_ms = int((time.time() - start_time) * 1000)
                logger.warning(
                    f"Sync timed out after {duration_ms}ms "
                    f"(timeout={self.config.sync_timeout_seconds}s)"
                )
                return False
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                logger.error(f"Sync error after {duration_ms}ms: {e}", exc_info=True)
                return False

    def get_all_tasks(self) -> List[taskchampion.Task]:
        """
        Get all tasks from replica.

        IMPORTANT: This must be called from the main event loop thread,
        not from a thread pool executor, since Replica is not thread-safe.

        Returns:
            List of TaskChampion Task objects

        Raises:
            ReplicaError: If task retrieval fails
        """
        try:
            replica = self._get_replica()
            # all_tasks() returns a dict[str, Task], convert to list
            tasks_dict = replica.all_tasks()
            return list(tasks_dict.values())
        except Exception as e:
            logger.error(f"Failed to retrieve tasks from replica: {e}", exc_info=True)
            raise ReplicaError(f"Failed to retrieve tasks: {e}") from e

    def get_last_sync_time(self) -> Optional[datetime]:
        """Get timestamp of last successful sync."""
        return self._last_sync_success


# Global replica manager instance
_replica_manager: Optional[ReplicaManager] = None


def get_replica_manager() -> ReplicaManager:
    """Get the global replica manager instance."""
    global _replica_manager
    if _replica_manager is None:
        _replica_manager = ReplicaManager()
    return _replica_manager
