# TaskChampion Inky Bridge

Docker setup: sync server plus a small read-only HTTP JSON API for TaskChampion tasks (e.g. for a Pimoroni Inky Frame).

Two services:

- **taskchampion-sync-server** — official TaskChampion sync server (Taskwarrior 3 backend)
- **inky-bridge** — trusted client replica that holds the encryption secret and exposes tasks via REST

The bridge keeps a local replica of your encrypted data and serves it as JSON, matching Taskwarrior’s “overview” report (pending only, sorted by project then entry).

## Architecture

See [architecture.md](architecture.md) for detailed architecture documentation.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- A TaskChampion encryption secret
- TaskChampion client ID for the bridge replica
- Taskwarrior 3.0+ installed on local machines you want to sync (see [Configuring Taskwarrior Clients](#configuring-taskwarrior-clients))

### Setup

1. **Clone the repository**

```bash
git clone <repository-url>
cd taskwarrior-api
```

2. **Configure environment variables**

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
# Edit .env with your configuration
```

Required variables:
- `TASKCHAMPION_SYNC_SERVER_URL`: URL of the sync server (default: `http://sync-server:8080` for internal Docker networking)
- `TASKCHAMPION_CLIENT_ID`: Client ID for the bridge replica (must match the client ID used by your Taskwarrior clients - see [Configuring Taskwarrior Clients](#configuring-taskwarrior-clients))
- `TASKCHAMPION_ENCRYPTION_SECRET`: Encryption secret (must match your Taskwarrior `sync.encryption_secret`)

Optional variables:
- `ALLOW_CLIENT_IDS`: Comma-separated list of client IDs allowed to connect to the sync server (leave empty to allow all)
- `DATA_DIR`: Replica storage directory (default: `/data/replica`)
- `SYNC_TIMEOUT_SECONDS`: Sync timeout (default: `30`)
- `MIN_SYNC_INTERVAL_SECONDS`: Minimum sync interval (default: `10`)
- `AUTH_SECRET`: API authentication secret (optional)

Don’t commit `.env` — it contains secrets.

3. **Start the services**

```bash
docker compose up -d
```

4. **Verify services are running**

```bash
# Check sync server health (exposed on port 8080)
curl http://localhost:8080/health

# Check bridge health (exposed on port 8000, no sync triggered)
curl http://localhost:8000/health
```

Sync server is on 8080 for your reverse proxy; the bridge talks to it over the Docker network as `sync-server:8080`.

## Configuring Taskwarrior Clients

To sync your local Taskwarrior installation (e.g., on your work machine) with the sync server, you need to configure Taskwarrior 3.0+ with three key settings.

### Prerequisites

- Taskwarrior 3.0 or later installed on your local machine
- Access to your sync server URL (must be accessible from your local machine)
- A client ID (UUID) for your task database
- An encryption secret

### Step 1: Generate Client ID and Encryption Secret

**Client ID**: This identifies your task database (not your device!). All devices syncing the same tasks must use the **same** client ID.

Generate a UUID:
```bash
# On Linux/macOS
uuidgen

# Or use an online UUID generator
# Example: 85038910-8fe2-480d-b6cb-6e7fabc1fa44
```

**Encryption Secret**: This encrypts your tasks in transit. Generate a strong secret:

```bash
# Using pwgen (if installed)
pwgen -s 64 1

# Or use a password manager to generate a long random string
# Example: 4JQ!m3Irm8K1QvV^ATQVw0QEvCkbLX994hjoxQ&F1#jWl...
```

**Important**: 
- Use the **same** client ID on all devices that should share tasks
- Use the **same** encryption secret on all devices that should share tasks
- Keep the encryption secret secure and never share it

### Step 2: Configure Taskwarrior

Edit your Taskwarrior configuration file (typically `~/.taskrc` or `~/.config/task/taskrc`):

```bash
# Open your taskrc file
nano ~/.taskrc
# or
nano ~/.config/task/taskrc
```

Add the following configuration (replace with your values):

```bash
# Sync server URL (must include http:// or https://)
# If your sync server is behind a reverse proxy, use the proxy URL
sync.server.url=https://your-sync-server.example.com

# Client ID (same on all devices sharing tasks)
sync.server.client_id=85038910-8fe2-480d-b6cb-6e7fabc1fa44

# Encryption secret (same on all devices sharing tasks)
sync.encryption_secret=your-long-encryption-secret-here
```

**Note**: If your sync server is running locally via Docker Compose, you'll need to:
1. Expose the sync server through a reverse proxy (as mentioned in the scope, an external proxy already exists)
2. Use the proxy URL in `sync.server.url`
3. Ensure the proxy URL is accessible from your local machine

### Step 3: Configure the Bridge

Update your `.env` file to use the **same** client ID and encryption secret:

```bash
# In .env file
TASKCHAMPION_CLIENT_ID=85038910-8fe2-480d-b6cb-6e7fabc1fa44
TASKCHAMPION_ENCRYPTION_SECRET=your-long-encryption-secret-here
```

### Step 4: Initial Sync

**On your local machine** (work machine):

```bash
# Sync your local tasks to the server
task sync
```

This will:
1. Upload any local changes to the server
2. Download any changes from the server
3. Merge changes if needed

**On the bridge** (automatic):

The bridge will sync automatically when you make API requests to `/overview`. You can verify it's working:

```bash
curl http://localhost:8000/overview
```

Check the `meta.sync_ok` field in the response.

### Step 5: Verify Sync

**On your local machine**:

```bash
# Add a test task
task add "Test sync from work machine"

# Sync to server
task sync

# Verify the task appears
task list
```

**Via the bridge API**:

```bash
# Check if the task appears in the API
curl http://localhost:8000/overview | jq '.tasks[] | select(.description | contains("Test sync"))'
```

### Multiple Devices

To sync with multiple devices (e.g., laptop, desktop, phone):

1. **Use the same client ID** on all devices
2. **Use the same encryption secret** on all devices
3. **Use the same sync server URL** on all devices

Each device will maintain its own local replica, and `task sync` will synchronize changes between all devices.

### Important Notes

- **Client ID is NOT device-specific**: Despite its name, `client_id` identifies your task database, not your device. All devices sharing the same tasks must use the same client ID.
- **Two syncs required**: For a change to propagate from Device A to Device B:
  1. Run `task sync` on Device A (uploads change)
  2. Run `task sync` on Device B (downloads change)
- **Automatic sync**: Consider setting up a cron job or systemd timer to sync periodically:
  ```bash
  # Add to crontab (sync every 15 minutes)
  */15 * * * * /usr/bin/task sync > /dev/null 2>&1
  ```

### Troubleshooting Client Sync

**Sync fails with connection error**:
- Verify `sync.server.url` is correct and accessible
- Check if sync server is running: `docker compose ps`
- Verify network connectivity to sync server

**Tasks not syncing between devices**:
- Verify all devices use the **same** `client_id`
- Verify all devices use the **same** `encryption_secret`
- Run `task sync` on both devices
- Check sync server logs: `docker compose logs sync-server`

**"Already synced with bad settings"**:
If you previously synced with incorrect settings (e.g., different client IDs), you may need to reset sync metadata:

```bash
# Backup your tasks first!
task export > backup.json

# Clear sync metadata (WARNING: This resets sync state)
# You may need to delete sync-related files in your task data directory
# Location depends on your data.location setting
```

**Bridge shows stale data**:
- Check bridge logs: `docker compose logs inky-bridge`
- Verify bridge `.env` has same client ID and encryption secret as Taskwarrior
- Manually trigger sync by calling `/overview` endpoint

## Configuration

Config is via environment variables; see `.env.example` for all options. Docker Compose injects your `.env` into the bridge. Don’t commit `.env` (keep it in `.gitignore`).

### Sync Server Access Control

The sync server identifies users by the `client_id` that clients send when connecting. The server does **not** have its own client ID. 

Optionally, you can restrict which client IDs are allowed to connect using the `ALLOW_CLIENT_IDS` environment variable (comma-separated list). If not set or empty, the server accepts connections from any client ID. This provides basic access control at the application level.

### Persistent Storage

Two Docker volumes are created:

- `sync-server-data`: Stores sync server data
- `inky-bridge-data`: Stores the bridge's local replica

These volumes persist across container restarts.

## Security Model

### End-to-End Encryption

Tasks are encrypted with your secret before they hit the sync server; the server never sees plaintext. The bridge holds the secret and keeps a local replica, so only the bridge can decrypt and serve task data.

### API Authentication

Optional API authentication can be enabled by setting `AUTH_SECRET`. When enabled, all API requests must include:

```
Authorization: Bearer <AUTH_SECRET>
```

### Secrets

Encryption secret lives in `TASKCHAMPION_ENCRYPTION_SECRET` in `.env`. Don’t commit `.env`, don’t log secrets or decrypted payloads. Replica data is on a persistent volume.

## On-Demand Sync Behavior

Every request to `/overview` triggers a sync attempt with the following safeguards:

1. **Single-Flight Lock**: Concurrent requests share a single sync operation
2. **Timeout Protection**: Sync operations timeout after `SYNC_TIMEOUT_SECONDS`
3. **Min Interval**: Syncs are skipped if the last sync was within `MIN_SYNC_INTERVAL_SECONDS`
4. **Stale Fallback**: If sync fails or times out, the API still returns the last local data with `meta.stale=true`

## API Documentation

### GET /overview

Same semantics as Taskwarrior’s overview report:

- **Filter**: `status == "pending"`
- **Sort**: `project` ascending, then `entry` timestamp ascending

**Response**:

```json
{
  "meta": {
    "sync_ok": true,
    "stale": false,
    "last_sync_at": "2026-01-27T08:00:23+01:00",
    "duration_ms": 245
  },
  "tasks": [
    {
      "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "short_id": "a1b2c3d4",
      "description": "Review PR #123",
      "status": "pending",
      "project": "work",
      "active": false,
      "timestamps": {
        "entry": "2026-01-20T10:00:00+01:00",
        "modified": "2026-01-25T14:30:00+01:00",
        "scheduled": null,
        "start": null,
        "wait": null
      }
    }
  ]
}
```

**Meta**: `sync_ok` (sync succeeded), `stale` (sync failed or timed out), `last_sync_at` (ISO 8601, Europe/Zurich), `duration_ms` (sync duration).

### GET /health

Liveness check. Does not run a sync.

**Response**:

```json
{
  "status": "healthy",
  "last_sync_at": "2026-01-27T08:00:23+01:00",
  "replica_path": "/data/replica"
}
```

## Task Object Schema

All task objects follow this normalized schema:

- `uuid` (string): Task UUID
- `short_id` (string): First 8 chars of UUID
- `description` (string): Task description
- `status` (string): e.g. `pending`, `completed`, `deleted`
- `project` (string or null): Taskwarrior project/area
- `active` (boolean): `true` when the task has been started (`task start`) and not yet completed; `false` otherwise
- `timestamps` (object):
  - `entry` (string): ISO 8601 timestamp (Europe/Zurich)
  - `modified` (string): ISO 8601 timestamp (Europe/Zurich)
  - `scheduled` (string or null): ISO 8601 timestamp or null
  - `start` (string or null): when set, task is active (started with `task start`); ISO 8601 (Europe/Zurich) or null
  - `wait` (string or null): ISO 8601 timestamp or null

Timestamps are ISO 8601 in Europe/Zurich (`+01:00` / `+02:00`). Nulls are `null`, not omitted.

## Logging

Structured logs: request path, response status/duration, sync start/end/fail and duration. INFO for normal ops, WARNING for sync failures/timeouts, ERROR for exceptions. Secrets and decrypted payloads are never logged.

## Troubleshooting

### Sync Failures

If you see **"Failed to synchronize with server"** (RuntimeError from taskchampion-py):

1. **Client ID and encryption secret** — The bridge must use the **same** `TASKCHAMPION_CLIENT_ID` and `TASKCHAMPION_ENCRYPTION_SECRET` as your Taskwarrior client. Copy `sync.server.client_id` and `sync.encryption_secret` from your taskrc (or `task show`) into `.env`.
2. **Sync server allow-list** — If `ALLOW_CLIENT_IDS` is set on the sync-server, the bridge’s client ID must be in that list.
3. **Sync server logs** — Run `docker compose logs sync-server` (or `docker logs sync-server`) and look for rejections or errors when the bridge connects.
4. **Reachability** — From the bridge container, the sync server must be reachable at `TASKCHAMPION_SYNC_SERVER_URL` (e.g. `http://sync-server:8080` on the Compose network). If you changed the sync-server port or hostname, update the bridge’s env.

If syncs are failing for other reasons, also verify the sync server URL and that the sync-server container is running.

### Stale Data

If `meta.stale=true` in responses:

1. Check sync server is running: `docker compose ps`
2. Check network connectivity between bridge and sync server
3. Review sync timeout settings (`SYNC_TIMEOUT_SECONDS`)
4. Check bridge logs: `docker compose logs inky-bridge`

### API Authentication

If authentication is enabled and requests are failing:

1. Verify `AUTH_SECRET` is set correctly
2. Include `Authorization: Bearer <secret>` header in requests
3. Check logs for authentication errors

## Development

### Building the Bridge

```bash
cd inky-bridge
docker build -t inky-bridge .
```

### Running Tests

Manual testing:

```bash
# Start services
docker compose up -d

# Test endpoints
curl http://localhost:8000/health
curl http://localhost:8000/overview
```

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f inky-bridge
docker compose logs -f sync-server
```

## License

MIT — see [LICENSE](LICENSE).
