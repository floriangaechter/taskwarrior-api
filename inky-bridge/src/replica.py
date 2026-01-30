"""Replica + sync: single-flight, timeout, min interval, stale fallback."""

import asyncio
import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import taskchampion

from .config import get_config
from .exceptions import ReplicaError

logger = logging.getLogger(__name__)

SYNC_RETRY_ATTEMPTS = 3
SYNC_RETRY_DELAY_SECONDS = 2
CONSECUTIVE_FAILURES_BEFORE_RESET = 3


class ReplicaManager:
    def __init__(self):
        self.config = get_config()
        self._replica: Optional[taskchampion.Replica] = None
        self._replica_lock = asyncio.Lock()  # Lock for replica access
        self._sync_lock = asyncio.Lock()
        self._last_sync_time: Optional[float] = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sync")
        self._last_sync_success: Optional[datetime] = None
        self._consecutive_sync_failures = 0

    def _get_replica(self) -> taskchampion.Replica:
        """Replica is not thread-safe; only call from main thread, not from executor."""
        if self._replica is None:
            logger.info(f"Initializing replica at {self.config.data_dir}")
            self._replica = taskchampion.Replica.new_on_disk(
                self.config.data_dir, True
            )
        return self._replica

    def _reset_replica_dir(self, data_dir: str) -> None:
        """Clear replica directory so next sync starts from scratch. Call from sync thread only."""
        path = Path(data_dir)
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Replica directory reset at {data_dir}")
        except Exception as e:
            logger.error(f"Failed to reset replica directory {data_dir}: {e}", exc_info=True)

    def _sync_blocking(
        self,
        data_dir: str,
        sync_server_url: str,
        client_id: str,
        encryption_secret: str,
        reset_first: bool = False,
    ) -> bool:
        """Blocking sync in thread pool; uses a fresh Replica in this thread (not shared). Retries on transient failure."""
        if reset_first:
            self._reset_replica_dir(data_dir)

        last_error: Optional[Exception] = None
        for attempt in range(1, SYNC_RETRY_ATTEMPTS + 1):
            try:
                logger.info(
                    f"Sync attempt {attempt}/{SYNC_RETRY_ATTEMPTS} at {data_dir} with {sync_server_url}"
                )
                replica = taskchampion.Replica.new_on_disk(data_dir, True)
                replica.sync_to_remote(
                    sync_server_url,
                    client_id,
                    encryption_secret,
                    False,  # avoid_snapshots = False
                )
                logger.info("Sync completed successfully")
                return True
            except RuntimeError as e:
                last_error = e
                if "synchronize with server" in str(e) and attempt < SYNC_RETRY_ATTEMPTS:
                    logger.warning(
                        f"Sync attempt {attempt} failed, retrying in {SYNC_RETRY_DELAY_SECONDS}s: {e}"
                    )
                    time.sleep(SYNC_RETRY_DELAY_SECONDS)
                else:
                    logger.error(
                        f"Sync failed: {e} (server={sync_server_url}, client_id={client_id[:8]}...)",
                        exc_info=(attempt == SYNC_RETRY_ATTEMPTS),
                    )
                    return False
            except Exception as e:
                last_error = e
                logger.error(f"Sync failed: {e}", exc_info=True)
                return False
        if last_error:
            logger.error(f"Sync failed after {SYNC_RETRY_ATTEMPTS} attempts: {last_error}")
        return False

    async def sync_with_timeout(self) -> bool:
        """Single-flight sync with timeout; returns True if sync succeeded."""
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

            # After consecutive failures, reset replica and try once from scratch
            reset_first = self._consecutive_sync_failures >= CONSECUTIVE_FAILURES_BEFORE_RESET
            if reset_first:
                logger.warning(
                    f"Consecutive sync failures ({self._consecutive_sync_failures}), "
                    "resetting replica and re-syncing from server"
                )
                self._consecutive_sync_failures = 0
                self._replica = None  # main thread must not use old replica after reset

            try:
                success = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        self._executor,
                        lambda: self._sync_blocking(
                            self.config.data_dir,
                            self.config.sync_server_url,
                            self.config.client_id,
                            self.config.encryption_secret,
                            reset_first,
                        ),
                    ),
                    timeout=self.config.sync_timeout_seconds,
                )
                duration_ms = int((time.time() - start_time) * 1000)
                if success:
                    logger.info(f"Sync succeeded in {duration_ms}ms")
                    self._last_sync_success = datetime.utcnow()
                    self._consecutive_sync_failures = 0
                    self._replica = None
                else:
                    self._consecutive_sync_failures += 1
                    logger.warning(
                        f"Sync failed after {duration_ms}ms "
                        f"(consecutive failures: {self._consecutive_sync_failures})"
                    )
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
        """Call from main thread only (Replica not thread-safe). Raises ReplicaError on failure."""
        try:
            replica = self._get_replica()
            # all_tasks() returns a dict[str, Task], convert to list
            tasks_dict = replica.all_tasks()
            return list(tasks_dict.values())
        except Exception as e:
            logger.error(f"Failed to retrieve tasks from replica: {e}", exc_info=True)
            raise ReplicaError(f"Failed to retrieve tasks: {e}") from e

    def get_last_sync_time(self) -> Optional[datetime]:
        return self._last_sync_success


_replica_manager: Optional[ReplicaManager] = None


def get_replica_manager() -> ReplicaManager:
    global _replica_manager
    if _replica_manager is None:
        _replica_manager = ReplicaManager()
    return _replica_manager
