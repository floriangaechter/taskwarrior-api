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

Tasks are keyed by UUID; we also expose `short_id` (first 8 chars). Status: `pending`, `completed`, `deleted`, `recurring`. `active` is true when the task has a start timestamp (started with `task start`). Timestamps (entry, modified, scheduled, start, wait) are UTC in the replica, exposed as Europe/Zurich ISO 8601; nulls are `null`.

## Overview report

Filter: `status == "pending"`. Sort: `project` ascending, then `entry` ascending. Matches Taskwarrior’s overview.

---

## Client integration (display project)

This section gives another project (e.g. an Inky Frame display app) everything needed to call the bridge API and render the task list. Copy or reference this when building the display client.

### Base URL and endpoints

- **Base URL**: The bridge is an HTTP JSON API. From the host running Docker, the default is `http://localhost:8089` (Compose maps host 8089 → container 8000). From another machine or the Inky device, use the hostname/IP and port where the bridge is exposed (e.g. `http://192.168.1.10:8089` or your reverse-proxy URL).
- **GET /overview** — Main endpoint for the task list. Triggers a sync, then returns pending tasks. Use this for the display.
- **GET /health** — Liveness; does not trigger sync. Use for startup checks or monitoring.

### Authentication

- If the bridge is run with **AUTH_SECRET** set, every request must include:
  ```http
  Authorization: Bearer <AUTH_SECRET>
  ```
  Missing or wrong token → **401 Unauthorized**.
- If **AUTH_SECRET** is not set, no header is required.

### GET /overview — request and response

**Request**: `GET /overview` (no query parameters). Optional header: `Authorization: Bearer <secret>` if auth is enabled.

**Response**: `200 OK`, JSON body:

```json
{
  "meta": {
    "sync_ok": true,
    "stale": false,
    "last_sync_at": "2026-01-30T15:00:00+01:00",
    "duration_ms": 245
  },
  "tasks": [
    {
      "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "short_id": "a1b2c3d4",
      "description": "Review PR #123",
      "status": "pending",
      "project": "work",
      "active": true,
      "timestamps": {
        "entry": "2026-01-20T10:00:00+01:00",
        "modified": "2026-01-25T14:30:00+01:00",
        "scheduled": null,
        "start": "2026-01-30T14:00:00+01:00",
        "wait": null
      }
    }
  ]
}
```

- **meta.sync_ok** (boolean): `true` if the last sync succeeded.
- **meta.stale** (boolean): `true` if sync failed or timed out; data is still returned but may be outdated. Safe to show a “data may be stale” hint.
- **meta.last_sync_at** (string or null): ISO 8601 (Europe/Zurich) of last successful sync.
- **meta.duration_ms** (number): Sync duration in milliseconds.
- **tasks** (array): Pending tasks only, already sorted by `project` ascending, then `entry` ascending.

### Task object (for display)

| Field | Type | Meaning |
|-------|------|--------|
| `uuid` | string | Unique task ID. |
| `short_id` | string | First 8 chars of UUID (e.g. for labels). |
| `description` | string | Task title/description. |
| `status` | string | Always `"pending"` in overview. |
| `project` | string or null | Taskwarrior project/area; use for grouping or section headers. |
| `active` | boolean | **`true`** = task has been started (`task start`), i.e. “currently working on”; **`false`** = waiting. Use this to distinguish active vs waiting (e.g. show active first or highlight). |
| `timestamps` | object | All ISO 8601 in Europe/Zurich (`+01:00` / `+02:00`). |
| `timestamps.entry` | string | When the task was created. |
| `timestamps.modified` | string | Last modification. |
| `timestamps.scheduled` | string or null | Scheduled start, if set. |
| `timestamps.start` | string or null | When the task was started (`task start`); set iff `active` is true. |
| `timestamps.wait` | string or null | Wait-until time, if set. |

Nulls are JSON `null`, not omitted.

### Display semantics

- **Filter/sort**: The API already returns only pending tasks, sorted by `project` then `entry`. No client-side filter or sort required for a basic list.
- **Active vs waiting**: Use `task.active` (or `task.timestamps.start !== null`) to show “in progress” vs “waiting” (e.g. active at top, or different style).
- **Grouping**: Optionally group by `task.project`; order within a project follows the response order (by entry).
- **Stale data**: If `meta.stale === true`, you can show a small “data may be outdated” indicator; still render `tasks` as usual.

### Error handling

| Status | Meaning |
|--------|--------|
| 200 | Success; body has `meta` and `tasks` (possibly empty). |
| 401 | Unauthorized; send valid `Authorization: Bearer <AUTH_SECRET>`. |
| 500 / 503 | Server or config error; retry or show error message. |

### Example: fetch and use in code

```bash
# No auth
curl -s http://localhost:8089/overview

# With auth
curl -s -H "Authorization: Bearer YOUR_AUTH_SECRET" http://localhost:8089/overview
```

Client logic (pseudocode):

1. `GET <base_url>/overview` (with `Authorization` header if auth is enabled).
2. On 200: parse JSON; render `response.tasks` (e.g. list or by `project`).
3. Use `task.active` to style or order “active” vs “waiting”.
4. If `response.meta.stale` is true, optionally show a stale indicator.
5. On 401: fix or prompt for token. On 5xx: retry or show error.

### CORS

The bridge allows all origins (`allow_origins=["*"]`). If the display is a web app on another origin, it can call the API without CORS issues. For an Inky/embedded device doing direct HTTP, CORS does not apply.

---

## Security

Encryption secret is in `TASKCHAMPION_ENCRYPTION_SECRET` (env, from `.env`). Not logged or exposed. Optional API auth: set `AUTH_SECRET`, send `Authorization: Bearer <secret>`. We don’t log secrets or decrypted payloads; we do log sync start/end/fail and durations. Sync server is on the Docker network; bridge is on 8000 (put a reverse proxy in front if you need HTTPS/access control).

## Scaling

One replica per bridge. To run multiple bridges, give each its own client ID and replica; they all talk to the same server. FastAPI handles concurrency; the sync lock and min interval keep sync from running away. Reads are local SQLite; storage size is proportional to task count.

Possible later: WAITING in overview filter, other reports, response caching, Prometheus metrics, webhooks, or multiple replicas per bridge.
