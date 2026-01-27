# Architecture Documentation

## System Overview

The TaskChampion Inky Bridge system consists of two Docker services working together to provide a read-only HTTP JSON API for TaskChampion tasks:

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

## Why the Bridge Must Be a Replica Client

### End-to-End Encryption Model

TaskChampion uses end-to-end encryption for task data:

1. **Encryption Secret**: A shared secret known only to trusted clients (not the server)
2. **Server Blindness**: The sync server stores encrypted data but cannot decrypt it
3. **Client Decryption**: Only clients holding the encryption secret can decrypt task data

### Replica vs. Cache

The bridge is **not** a simple cache or proxy. It must be a **full TaskChampion replica** because:

1. **Decryption Requirement**: To expose plaintext task data via the API, the bridge must decrypt tasks
2. **Secret Ownership**: The bridge holds the encryption secret, making it a trusted client
3. **Local Storage**: The bridge maintains a persistent local replica (SQLite database) of all task data
4. **Sync Protocol**: The bridge uses the TaskChampion sync protocol (via `taskchampion-py`) to synchronize with the server

This is fundamentally different from a reverse proxy or API gateway that would simply forward encrypted data.

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
   │   ├─ Apply overview filter (status==pending, exclude someday)
   │   └─ Apply overview sort (tags_sort_key, entry)
   │
8. Return JSON response with meta and tasks
```

### Sync Flow Details

The sync operation follows the TaskChampion sync protocol:

1. **Download Phase**: The replica downloads encrypted operations from the server since its last sync
2. **Decrypt Phase**: Operations are decrypted using the encryption secret
3. **Apply Phase**: Decrypted operations are applied to the local replica
4. **Gather Phase**: The replica gathers any local changes (though the bridge is read-only, so this is typically empty)
5. **Encrypt Phase**: Local changes are encrypted
6. **Upload Phase**: Encrypted changes are uploaded to the server

### Query Flow Details

After sync completes (or fails), the API queries the local replica:

1. **Retrieve Tasks**: Get all tasks from the replica using `replica.all_tasks()`
2. **Normalize**: Convert TaskChampion Task objects to normalized Task models:
   - Extract UUID, description, status, tags
   - Convert timestamps to ISO 8601 with Europe/Zurich timezone
   - Generate `tags_sort_key` for deterministic sorting
3. **Filter**: Apply overview filter (status==pending, exclude someday tag)
4. **Sort**: Sort by `tags_sort_key` ascending, then `entry` timestamp ascending
5. **Serialize**: Convert to JSON using Pydantic models

## Sync Safeguards

### Single-Flight Lock

**Problem**: Concurrent requests could trigger multiple simultaneous syncs, wasting resources and potentially causing conflicts.

**Solution**: Use `asyncio.Lock()` to ensure only one sync runs at a time. Concurrent requests wait for the active sync to complete and share its results.

**Implementation**: The lock is acquired before sync, and released after sync completes (or fails).

### Timeout Protection

**Problem**: Sync operations could hang indefinitely if the server is unreachable or slow.

**Solution**: Wrap sync in `asyncio.wait_for()` with configurable timeout (`SYNC_TIMEOUT_SECONDS`, default 30s).

**Behavior**: If sync times out:
- Sync is cancelled
- Last known good data is returned
- `meta.stale=true` is set in the response
- Error is logged

### Minimum Sync Interval

**Problem**: Rapid repeated requests could trigger excessive syncs.

**Solution**: Track last sync time and skip sync if within `MIN_SYNC_INTERVAL_SECONDS` (default 10s).

**Behavior**: 
- Before sync, check if last sync was recent
- If recent, skip sync and return cached data
- Double-check after acquiring lock (another request may have synced)

### Stale Fallback

**Problem**: If sync fails or times out, the API should still return useful data.

**Solution**: Always return the last locally available data, even if sync failed.

**Behavior**:
- On sync failure/timeout: `meta.sync_ok=false`, `meta.stale=true`
- On sync success: `meta.sync_ok=true`, `meta.stale=false`
- `meta.last_sync_at` indicates when data was last successfully synced

## Failure Modes and Mitigations

### Sync Server Unavailable

**Symptoms**:
- Sync operations timeout or fail
- `meta.stale=true` in responses
- Error logs: "Sync failed" or "Sync timed out"

**Mitigation**:
- API continues to serve last known good data
- No impact on API availability
- Sync retries on next request

**Recovery**:
- Fix sync server connectivity
- Next request will sync successfully
- `meta.stale` becomes `false`

### Network Issues

**Symptoms**:
- Intermittent sync failures
- Timeouts
- Connection errors

**Mitigation**:
- Timeout protection prevents indefinite hangs
- Stale data fallback ensures API remains responsive
- Single-flight lock prevents resource waste

**Recovery**:
- Network issues resolve automatically
- Next successful sync updates data

### Encryption Secret Mismatch

**Symptoms**:
- Sync fails with decryption errors
- Cannot decrypt data from server

**Mitigation**:
- Validation at startup (fails fast)
- Clear error messages in logs
- Service won't start with invalid secret

**Recovery**:
- Update encryption secret in Docker secret file
- Restart service

### Replica Corruption

**Symptoms**:
- Errors reading tasks from replica
- Database errors

**Mitigation**:
- Replica uses SQLite with transaction safety
- TaskChampion handles corruption recovery
- Persistent volume ensures data durability

**Recovery**:
- TaskChampion may auto-recover
- If not, delete replica volume and resync (data loss possible)

### High Request Load

**Symptoms**:
- Multiple concurrent requests
- Potential for many sync attempts

**Mitigation**:
- Single-flight lock ensures only one sync
- Min sync interval prevents rapid syncs
- Concurrent requests share sync results

**Behavior**:
- First request triggers sync
- Concurrent requests wait for sync
- All requests return same data

## Data Model

### Task Identity

Tasks are identified by **UUID** (not numeric IDs):

- **UUID**: Stable, globally unique identifier
- **short_id**: First 8 characters of UUID for display convenience
- **Rationale**: Numeric IDs are not stable across replicas and must not be relied upon

### Task Status

Tasks have a `status` field:
- `pending`: Active task
- `completed`: Completed task
- `deleted`: Deleted task
- `recurring`: Recurring task template

### Tags

Tasks have zero or more tags:
- Tags are strings
- Tags are sorted for deterministic `tags_sort_key`
- Special tags: `someday` (excluded from overview), `WAITING` (future support)

### Timestamps

All timestamps are stored as UTC internally and converted to Europe/Zurich for API responses:

- **entry**: When task was created
- **modified**: Last modification time
- **scheduled**: Scheduled start time (nullable)
- **wait**: Wait until time (nullable)

Timezone conversion:
- UTC → Europe/Zurich (DST-aware: +01:00 or +02:00)
- ISO 8601 format: `2026-01-27T08:00:23+01:00`
- Null timestamps returned as `null` (not omitted)

## Overview Report Semantics

The `/overview` endpoint implements Taskwarrior's "overview" report:

### Filter

- Include: `status == "pending"`
- Exclude: Tasks with tag `"someday"`
- Future: Design allows adding `OR tag == "WAITING"` without schema changes

### Sort

1. `tags_sort_key` ascending (deterministic: `",".join(sorted(tags))`)
2. `entry` timestamp ascending

### Rationale

This matches Taskwarrior's overview report behavior, providing a consistent view of active tasks (excluding "someday" tasks) sorted by tags and creation time.

## Security Considerations

### Encryption Secret Storage

- Stored as Docker secret file (not environment variable)
- Mounted read-only into container
- Never logged or exposed in API responses

### API Authentication

- Optional shared-secret authentication
- Bearer token in `Authorization` header
- Can be disabled for trusted networks

### Logging

- Never log encryption secrets
- Never log full decrypted task payloads
- Log sync operations, durations, failures
- Structured logging for observability

### Network Security

- Sync server not exposed externally (internal Docker network)
- Bridge exposed on port 8000 (behind external proxy)
- No reverse proxy included (handled externally)

## Scalability Considerations

### Single Replica

The bridge maintains a single replica. For multiple bridges:

- Each bridge needs its own `TASKCHAMPION_CLIENT_ID`
- Each bridge maintains its own replica
- All bridges sync with the same server
- No coordination needed between bridges

### Request Concurrency

- FastAPI handles concurrent requests
- Single-flight sync lock prevents sync conflicts
- Query operations are fast (local SQLite)
- Sync operations are rate-limited by min interval

### Storage

- SQLite database stores replica data
- Persistent volume ensures durability
- Size depends on number of tasks
- TaskChampion handles database optimization

## Future Enhancements

Potential improvements:

1. **WAITING Tag Support**: Add `OR tag == "WAITING"` to overview filter
2. **Additional Reports**: Implement other Taskwarrior reports
3. **Caching**: Add response caching for frequently accessed data
4. **Metrics**: Add Prometheus metrics endpoint
5. **Webhooks**: Notify on sync completion
6. **Multi-Replica**: Support multiple replicas in one bridge instance
