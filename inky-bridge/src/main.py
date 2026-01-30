"""FastAPI app: /overview (sync-on-demand + overview tasks), /health."""

import logging
import time

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from .config import get_config
from .exceptions import ConfigurationError, InkyBridgeError, ReplicaError
from .filters import apply_overview_filter, apply_overview_sort, normalize_task
from .models import HealthResponse, OverviewResponse, SyncMeta, format_timestamp
from .replica import get_replica_manager

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Inky Bridge",
    description="Read-only HTTP JSON API for TaskChampion tasks",
    version="1.0.0",
)

# CORS middleware (allow all origins - adjust as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def check_auth(request: Request) -> None:
    config = get_config()
    if not config.requires_auth():
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header[7:]  # Remove "Bearer " prefix
    if token != config.auth_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    start_time = time.time()
    logger.info(f"Request: {request.method} {request.url.path}")
    response = await call_next(request)
    duration_ms = int((time.time() - start_time) * 1000)
    logger.info(f"Response: {response.status_code} ({duration_ms}ms)")
    return response


@app.get("/overview", response_model=OverviewResponse)
async def get_overview(request: Request) -> OverviewResponse:
    """Overview report (pending only, sort project+entry). Syncs on demand; on failure returns stale data."""
    check_auth(request)

    replica_manager = get_replica_manager()
    start_time = time.time()

    # Attempt sync (non-blocking, returns stale data on failure)
    sync_ok = await replica_manager.sync_with_timeout()
    duration_ms = int((time.time() - start_time) * 1000)

    # Get tasks from replica
    try:
        tasks_raw = replica_manager.get_all_tasks()
        logger.debug(f"Retrieved {len(tasks_raw)} tasks from replica")

        # Normalize tasks, skipping any that fail to normalize
        tasks = []
        for task in tasks_raw:
            try:
                normalized = normalize_task(task)
                tasks.append(normalized)
            except Exception as e:
                task_uuid = task.get_uuid() if hasattr(task, "get_uuid") else "unknown"
                logger.warning(f"Skipping task {task_uuid}: normalization failed: {e}")
                continue

        # Apply overview filter and sort
        filtered_tasks = apply_overview_filter(tasks)
        sorted_tasks = apply_overview_sort(filtered_tasks)

        # Build response
        last_sync = replica_manager.get_last_sync_time()
        meta = SyncMeta(
            sync_ok=sync_ok,
            stale=not sync_ok,
            last_sync_at=format_timestamp(last_sync) if last_sync else None,
            duration_ms=duration_ms,
        )

        return OverviewResponse(meta=meta, tasks=sorted_tasks)

    except ReplicaError as e:
        logger.error(f"Replica error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve tasks from replica",
        ) from e
    except Exception as e:
        logger.error(f"Unexpected error processing overview: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness; does not trigger sync."""
    try:
        replica_manager = get_replica_manager()
        config = get_config()
        last_sync = replica_manager.get_last_sync_time()

        return HealthResponse(
            status="healthy",
            last_sync_at=format_timestamp(last_sync) if last_sync else None,
            replica_path=config.data_dir,
        )
    except ConfigurationError as e:
        logger.error(f"Configuration error in health check: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service misconfigured",
        ) from e
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unhealthy",
        ) from e


@app.on_event("startup")
async def startup() -> None:
    logger.info("Starting inky-bridge")
    try:
        config = get_config()
        logger.info(f"Configuration loaded successfully")
        logger.info(f"  Sync server: {config.sync_server_url}")
        logger.info(f"  Replica directory: {config.data_dir}")
        logger.info(f"  Client ID: {config.client_id[:8]}...")
        logger.info(f"  Auth required: {config.requires_auth()}")
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Failed to initialize: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down inky-bridge")
