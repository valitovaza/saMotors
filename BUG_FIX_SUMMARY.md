# Bug Fix: Vehicle Disappearing After Page Refresh

## Problem

When creating a new vehicle in DealerOS:

1. ✓ Vehicle appears in stocks immediately after creation
2. ✗ Vehicle disappears after page refresh
3. Newly created vehicle is not visible when fetching `/api/state`

## Root Cause

The issue was related to **SQLite WAL (Write-Ahead Logging) mode** and **transaction visibility across connections**:

In WAL mode:

- Database writes go to the `.wal` file first, not the main `.db` file
- Changes are only visible to the **same connection** that made the write
- Other connections see the `.wal` file changes only after a **checkpoint** is performed
- The application was not explicitly checkpointing after writes
- When the frontend refreshed and made a new API call with a new database connection, it couldn't see the newly created vehicles written by the previous connection

## Solution Implemented

### 1. Enhanced WAL Configuration (app/db/init_db.py)

```python
def connect_sqlite(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA wal_autocheckpoint = 1000")  # ← NEW: Auto-checkpoint every 1000 pages
    return connection
```

- Added `PRAGMA wal_autocheckpoint = 1000` to automatically checkpoint every 1000 pages

### 2. Improved WAL Checkpoint Function (app/db/init_db.py)

```python
def checkpoint_wal(db_path: Path) -> None:
    """Checkpoint the WAL file to ensure data is visible across connections.

    In WAL mode, writes go to the .wal file first. This checkpoint moves them
    to the main database file so other connections can see the changes.
    """
    if not db_path.exists():
        return
    connection = sqlite3.connect(db_path)
    connection.isolation_level = None  # Enable autocommit mode for PRAGMA
    try:
        # Perform checkpoint with RESTART mode to ensure all data is synced
        # and the WAL file is reset
        result = connection.execute("PRAGMA wal_checkpoint(RESTART)").fetchone()
    except Exception as e:
        import sys
        print(f"WAL checkpoint warning: {e}", file=sys.stderr)
    finally:
        connection.close()
        time.sleep(0.01)  # Give filesystem a moment to sync data
```

- `PRAGMA wal_checkpoint(RESTART)` syncs WAL changes to main database and closes the WAL file
- Added error handling and filesystem sync delay
- Ensures all pending changes are immediately visible to new connections

### 3. Added Explicit Checkpoints After Critical Database Writes

Checkpoints added after `connection.commit()` in:

**app/services/state_service.py:**

- `create_vehicle()` - Creates new vehicles
- `complete_sale()` - Completes vehicle sales
- `create_finance_entry()` - Records expenses
- `create_collection_delivery()` - Logs collections/deliveries
- `update_investor_total_balance()` - Updates investor data

**app/services/ops_service.py:**

- `create_service_record()` - Records vehicle service

### 4. Added Cache-Busting Headers to /api/state (app/main.py)

```python
@app.get("/api/state")
def app_state() -> JSONResponse:
    state = build_app_state(LOCAL_DB)
    return JSONResponse(
        content=state,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
```

- Added HTTP headers to prevent any browser caching of state responses
- Ensures frontend always gets fresh data on refresh

### 5. Added Diagnostic Endpoint (app/main.py)

Created `/api/debug/db-status` endpoint to diagnose:

- Total vehicles in database
- Count of app-created vehicles
- Count of app-created vehicles in stock
- Comparison with what `/api/state` returns
- Helpful for troubleshooting data visibility issues

## Files Modified

1. ✓ `app/db/init_db.py` - Enhanced WAL checkpoint function with better error handling and sync delays
2. ✓ `app/db/__init__.py` - Exported checkpoint_wal function
3. ✓ `app/services/state_service.py` - Added checkpoints to vehicle/sale/finance operations
4. ✓ `app/services/ops_service.py` - Added checkpoints to ops operations
5. ✓ `app/main.py` - Added cache-busting headers to /api/state and diagnostic /api/debug/db-status endpoint

## Testing the Fix

The fix ensures that:

1. When a vehicle is created, it's committed to the database AND checkpointed
2. The checkpoint syncs the WAL file to the main database file
3. When the frontend refreshes and calls `/api/state`, a new database connection can immediately see the newly created vehicle
4. The user experience is now consistent - created vehicles persist after page refresh

## Performance Impact

- **Minimal**: Auto-checkpoint at 1000 pages means most small operations won't trigger extra I/O
- **Improved clarity**: Explicit checkpoints only on critical user-facing operations
- **Safety**: Ensures data consistency and visibility across the application
