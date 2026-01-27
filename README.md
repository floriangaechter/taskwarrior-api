# TaskChampion Inky Bridge

A Dockerized setup providing a read-only HTTP JSON API for TaskChampion tasks, designed for use with a Pimoroni Inky Frame display.

## Overview

This project consists of two services:

1. **taskchampion-sync-server**: The official TaskChampion sync server (Taskwarrior 3 / TaskChampion sync backend)
2. **inky-bridge**: A small read-only HTTP JSON API that acts as a trusted TaskChampion client replica

The bridge maintains a local replica of your encrypted task data and exposes it via a REST API, implementing the semantics of Taskwarrior's "overview" report.

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

2. **Create secrets directory**

```bash
mkdir -p secrets
echo "your-encryption-secret-here" > secrets/taskchampion_encryption_secret.txt
chmod 600 secrets/taskchampion_encryption_secret.txt
```

3. **Configure environment variables**

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
# Edit .env with your configuration
```

Required variables:
- `TASKCHAMPION_SYNC_SERVER_URL`: URL of the sync server (default: `http://sync-server:8080` for internal Docker networking)
- `TASKCHAMPION_CLIENT_ID`: Client ID for the bridge replica (must match the client ID used by your Taskwarrior clients - see [Configuring Taskwarrior Clients](#configuring-taskwarrior-clients))

Optional variables:
- `ALLOW_CLIENT_IDS`: Comma-separated list of client IDs allowed to connect to the sync server (leave empty to allow all). This provides basic access control - only clients with matching client IDs will be able to sync.

Optional variables:
- `DATA_DIR`: Replica storage directory (default: `/data/replica`)
- `SYNC_TIMEOUT_SECONDS`: Sync timeout (default: `30`)
- `MIN_SYNC_INTERVAL_SECONDS`: Minimum sync interval (default: `10`)
- `AUTH_SECRET`: API authentication secret (optional)

4. **Start the services**

```bash
docker compose up -d
```

5. **Verify services are running**

```bash
# Check sync server health (exposed on port 8080)
curl http://localhost:8080/health

# Check bridge health (exposed on port 8000, no sync triggered)
curl http://localhost:8000/health
```

**Note**: The sync server is exposed on port 8080 for your external reverse proxy to forward requests. The bridge uses the internal Docker network (`sync-server:8080`) to communicate with the sync server.

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
# Encryption secret goes in secrets/taskchampion_encryption_secret.txt
```

Also update `secrets/taskchampion_encryption_secret.txt` with the same encryption secret.

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
- Verify bridge uses same client ID and encryption secret
- Manually trigger sync by calling `/overview` endpoint

## Configuration

### Environment Variables

See `.env.example` for all available configuration options.

### Docker Secrets

The encryption secret is stored as a Docker secret file at `secrets/taskchampion_encryption_secret.txt`. This file is mounted into the container and read at startup.

**Important**: Never commit the secrets directory to version control. Add it to `.gitignore`.

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

- Task data is encrypted end-to-end using the encryption secret
- The sync server cannot decrypt task data
- The bridge holds the encryption secret and maintains a trusted replica
- Only the bridge can decrypt and expose plaintext task data

### API Authentication

Optional API authentication can be enabled by setting `AUTH_SECRET`. When enabled, all API requests must include:

```
Authorization: Bearer <AUTH_SECRET>
```

### Secrets Management

- Encryption secret is stored as a Docker secret file (not in environment variables)
- Never log encryption secrets or full decrypted task payloads
- Replica storage is mounted as a persistent volume

## On-Demand Sync Behavior

Every request to `/overview` triggers a sync attempt with the following safeguards:

1. **Single-Flight Lock**: Concurrent requests share a single sync operation
2. **Timeout Protection**: Sync operations timeout after `SYNC_TIMEOUT_SECONDS`
3. **Min Interval**: Syncs are skipped if the last sync was within `MIN_SYNC_INTERVAL_SECONDS`
4. **Stale Fallback**: If sync fails or times out, the API returns the last locally available data with `meta.stale=true`

This ensures the API remains responsive even if the sync server is unavailable.

## API Documentation

### GET /overview

Returns tasks matching the Taskwarrior "overview" report semantics:

- **Filter**: `status == "pending"` AND tag `"someday"` NOT present
- **Sort**: By `tags_sort_key` ascending, then `entry` timestamp ascending

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
      "tags": ["work", "urgent"],
      "tags_sort_key": "urgent,work",
      "timestamps": {
        "entry": "2026-01-20T10:00:00+01:00",
        "modified": "2026-01-25T14:30:00+01:00",
        "scheduled": null,
        "wait": null
      }
    }
  ]
}
```

**Meta Fields**:
- `sync_ok`: Whether the sync completed successfully
- `stale`: Whether the returned data is stale (sync failed/timed out)
- `last_sync_at`: ISO 8601 timestamp of last successful sync (Europe/Zurich timezone)
- `duration_ms`: Sync operation duration in milliseconds

### GET /health

Health check endpoint. Does NOT trigger a sync.

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

- `uuid` (string): Task UUID (primary identifier)
- `short_id` (string): First 8 characters of UUID for display convenience
- `description` (string): Task description
- `status` (string): Task status (e.g., `pending`, `completed`, `deleted`)
- `tags` (array of strings): List of task tags
- `tags_sort_key` (string): Deterministic sort key (`",".join(sorted(tags))`)
- `timestamps` (object):
  - `entry` (string): ISO 8601 timestamp (Europe/Zurich)
  - `modified` (string): ISO 8601 timestamp (Europe/Zurich)
  - `scheduled` (string or null): ISO 8601 timestamp or null
  - `wait` (string or null): ISO 8601 timestamp or null

### Timezone

All timestamps are returned in ISO 8601 format with Europe/Zurich timezone offset (DST-aware: `+01:00` or `+02:00` as appropriate).

Example: `2026-01-27T08:00:23+01:00`

Null timestamps are returned as `null` (not omitted).

## Logging

The bridge uses structured logging with the following log levels:

- `INFO`: Normal operations (requests, syncs)
- `WARNING`: Sync failures, timeouts
- `ERROR`: Errors, exceptions

Logs include:
- Request method and path
- Response status and duration
- Sync start/end/failure with durations
- Never includes secrets or full decrypted task payloads

## Troubleshooting

### Sync Failures

If syncs are failing:

1. Check sync server logs: `docker compose logs sync-server`
2. Verify sync server URL is correct
3. Check encryption secret is correct
4. Verify client IDs match your TaskChampion setup

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

[Add your license here]
