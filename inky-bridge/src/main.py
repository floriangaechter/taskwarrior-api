"""FastAPI app: /overview (sync-on-demand + overview tasks), /health."""

import logging
import time

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from .config import get_config
from .exceptions import ConfigurationError
from .filters import filter_and_sort_overview, task_data_to_model
from .models import HealthResponse, OverviewResponse, SyncMeta, format_timestamp
from .replica import get_replica_worker

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

    token = auth_header[7:]
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
    """Overview report (pending only, sort project+entry). Syncs on demand."""
    check_auth(request)

    worker = get_replica_worker()
    start_time = time.time()

    # Sync and read tasks in one operation
    result = worker.sync_and_read()
    duration_ms = int((time.time() - start_time) * 1000)

    # Convert TaskData to Task models and filter/sort
    try:
        tasks = [task_data_to_model(td) for td in result.tasks]
        filtered_sorted = filter_and_sort_overview(tasks)

        meta = SyncMeta(
            sync_ok=result.success,
            stale=not result.success,
            last_sync_at=format_timestamp(worker.last_sync_time),
            duration_ms=duration_ms,
        )

        return OverviewResponse(meta=meta, tasks=filtered_sorted)

    except Exception as e:
        logger.error(f"Error processing tasks: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process tasks",
        ) from e


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness check; does not trigger sync."""
    try:
        worker = get_replica_worker()
        config = get_config()

        return HealthResponse(
            status="healthy",
            last_sync_at=format_timestamp(worker.last_sync_time),
            replica_path=config.data_dir,
        )
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
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
        logger.info("Configuration loaded:")
        logger.info(f"  Sync server: {config.sync_server_url}")
        logger.info(f"  Replica dir: {config.data_dir}")
        logger.info(f"  Client ID: {config.client_id}")
        logger.info(f"  Secret length: {len(config.encryption_secret)}")
        logger.info(f"  Auth required: {config.requires_auth()}")
        
        # Initialize the worker (but don't sync yet)
        get_replica_worker()
        logger.info("Replica worker initialized")
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Startup failed: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down inky-bridge")
