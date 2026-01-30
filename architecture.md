# Architecture

Two Docker services: sync server and inky-bridge. The bridge is a read-only HTTP JSON API for TaskChampion tasks.

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│  Inky Frame     │────────▶│  inky-bridge     │────────▶│ sync-server     │
│  (Display)      │  HTTP   │  (Python API)    │  Sync   │  (Rust)         │
└─────────────────┘         └──────────────────┘         └─────────────────┘
                                     │
                                     │ Local Replica
                                     ▼
                            ┌──────────────────┐
                            │  SQLite Storage  │
                            │  (Persistent)    │
                            └──────────────────┘
```

## Why the bridge is a replica

TaskChampion encrypts task data end-to-end: only clients with the secret can decrypt. The sync server only stores ciphertext. So to serve plaintext over HTTP, the bridge has to be a real client: it holds the secret, keeps a local replica (SQLite), and syncs via `taskchampion-py`. A plain proxy would only forward encrypted blobs.

## Request Flow

### Overview Request Flow

```
1. Inky Frame → GET /overview
   │
2. FastAPI receives request
   │
3. Check authentication (if enabled)
   │
4. Acquire sync lock (single-flight)
   │
5. Check min sync interval
   │
6. Perform sync with timeout:
   │   ├─ Create server connection
   │   ├─ Download encrypted changes from server
   │   ├─ Decrypt changes using encryption secret
   │   ├─ Apply changes to local replica
   │   ├─ Gather local changes
   │   ├─ Encrypt local changes
   │   └─ Upload encrypted changes to server
   │
7. Query local replica:
   │   ├─ Get all tasks
   │   ├─ Normalize tasks (extract fields, convert timestamps)
   │   ├─ Apply overview filter (status==pending)
   │   └─ Apply overview sort (project, entry)
   │
8. Return JSON response with meta and tasks
```

Sync: download encrypted ops → decrypt with secret → apply to replica → (optionally) gather/encrypt/upload local changes (bridge is read-only so usually nothing to upload). Then we read from the replica: `all_tasks()`, normalize to our Task model (UUID, description, status, timestamps in Europe/Zurich, project), filter (pending only), sort (project, then entry), serialize to JSON.

## Sync safeguards

- **Single-flight**: `asyncio.Lock()` so only one sync runs at a time; concurrent callers wait and share the result.
- **Timeout**: Sync runs in `asyncio.wait_for(..., SYNC_TIMEOUT_SECONDS)` (default 30s). On timeout we cancel, return last good data, set `meta.stale=true`, log.
- **Min interval**: If the last sync was within `MIN_SYNC_INTERVAL_SECONDS` (default 10s), we skip sync and serve from replica. We re-check after taking the lock in case another request already synced.
- **Stale fallback**: On failure or timeout we still return the last local data; `meta.sync_ok`/`meta.stale` and `meta.last_sync_at` tell you what happened.

## Failure modes

- **Sync server down**: Sync times out or fails, `meta.stale=true`, we keep serving last good data. Fix connectivity and the next request will sync.
- **Network flakiness**: Same idea; timeout and stale fallback keep the API up. When the network is back, the next sync succeeds.
- **Wrong encryption secret**: Sync fails with decryption errors. We validate at startup so misconfiguration fails fast; fix `TASKCHAMPION_ENCRYPTION_SECRET` in `.env` and restart.
- **Replica corruption**: TaskChampion/SQLite handle it when they can. If not, you may need to delete the replica volume and resync (possible data loss).
- **High load**: Single-flight + min interval mean we only run one sync at a time and don’t hammer the server; concurrent callers share the result.

## Data model

Tasks are keyed by UUID; we also expose `short_id` (first 8 chars). Status: `pending`, `completed`, `deleted`, `recurring`. Timestamps are UTC in the replica, exposed as Europe/Zurich ISO 8601; nulls are `null`.

## Overview report

Filter: `status == "pending"`. Sort: `project` ascending, then `entry` ascending. Matches Taskwarrior’s overview.

## Security

Encryption secret is in `TASKCHAMPION_ENCRYPTION_SECRET` (env, from `.env`). Not logged or exposed. Optional API auth: set `AUTH_SECRET`, send `Authorization: Bearer <secret>`. We don’t log secrets or decrypted payloads; we do log sync start/end/fail and durations. Sync server is on the Docker network; bridge is on 8000 (put a reverse proxy in front if you need HTTPS/access control).

## Scaling

One replica per bridge. To run multiple bridges, give each its own client ID and replica; they all talk to the same server. FastAPI handles concurrency; the sync lock and min interval keep sync from running away. Reads are local SQLite; storage size is proportional to task count.

Possible later: WAITING in overview filter, other reports, response caching, Prometheus metrics, webhooks, or multiple replicas per bridge.
