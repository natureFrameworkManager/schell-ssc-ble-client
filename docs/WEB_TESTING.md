# Testing the web app without installing it

This guide runs the FastAPI service and frontend directly from the source
checkout. It does **not** run `pip install -e .`, does not install the
`ssc-web` console script, and does not install a systemd service.

Web dependencies still need to be present in a virtual environment.

## 1. Prepare dependencies

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-web.txt
```

If the virtual environment already has these packages, skip the install step.

## 2. Use a copy of the database

Testing against a copy avoids any accidental change to the real recorder data.
Use SQLite's backup API from Python:

```bash
.venv/bin/python - <<'PY'
import sqlite3

source = sqlite3.connect("/var/lib/ssc-recorder/ssc.sqlite3")
target = sqlite3.connect("/tmp/ssc-web-test.sqlite3")
source.backup(target)
target.close()
source.close()
print("Wrote /tmp/ssc-web-test.sqlite3")
PY
```

If the recorder has never run, use a database that already has the recorder
schema but no devices (or run the recorder once against test hardware). A
completely missing database is reported as unavailable, not as an empty
dashboard.

## 3. Start the web app from source

Run from the repository root. `PYTHONPATH=.` makes the local `ssc` package
importable without installing it.

```bash
PYTHONPATH=. .venv/bin/python -m ssc.web \
    --config deploy/ssc-web.toml \
    --database /tmp/ssc-web-test.sqlite3 \
    --host 127.0.0.1 \
    --port 8000
```

Alternative, using uvicorn directly:

```bash
SSC_WEB_DATABASE=/tmp/ssc-web-test.sqlite3 \
PYTHONPATH=. .venv/bin/uvicorn ssc.web.app:app \
    --host 127.0.0.1 --port 8000 --reload
```

Open:

- Dashboard: <http://127.0.0.1:8000/>
- API documentation: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/api/v1/health>

Stop the server with `Ctrl+C`.

## 4. Manual API checks

```bash
curl -s http://127.0.0.1:8000/api/v1/health | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/v1/devices | python3 -m json.tool

curl -s 'http://127.0.0.1:8000/api/v1/devices/1/presence?from=2026-11-01T00:00:00Z&to=2026-12-01T00:00:00Z' \
    | python3 -m json.tool

curl -s http://127.0.0.1:8000/api/v1/devices/1/state/current \
    | python3 -m json.tool

curl -s http://127.0.0.1:8000/api/v1/devices/1/snapshots?limit=10 \
    | python3 -m json.tool

# CSV, one dataset
curl -o /tmp/ssc-daily.csv \
    'http://127.0.0.1:8000/api/v1/devices/1/export?format=csv&datasets=daily&from=2026-11-01T00:00:00Z&to=2026-12-01T00:00:00Z'

# CSV, multiple datasets (returns a ZIP)
curl -o /tmp/ssc-export.zip \
    'http://127.0.0.1:8000/api/v1/devices/1/export?format=csv&datasets=summary,presence,telemetry'

# JSON and XLSX
curl -o /tmp/ssc-export.json \
    'http://127.0.0.1:8000/api/v1/devices/1/export?format=json&datasets=telemetry,counters&pretty=true'
curl -o /tmp/ssc-export.xlsx \
    'http://127.0.0.1:8000/api/v1/devices/1/export?format=xlsx&datasets=summary,daily,events'

# PDF
curl -o /tmp/ssc-export.pdf \
    'http://127.0.0.1:8000/api/v1/devices/1/export?format=pdf&datasets=summary,presence,telemetry&pdf_page_size=a4&pdf_orientation=landscape'
```

Expected error cases:

- unknown device → `404`
- invalid date range where `from >= to` → `422`
- missing or unreadable database → `503`
- raw EEPROM when `raw_eeprom_download = false` → `403`
- comparing snapshots without stored EEPROM images → `409`

## 5. Manual browser checklist

### Startup

- Dashboard loads with no browser console errors.
- Header health badge changes from “checking…” to a known state.
- Static CSS, JavaScript and charts load.
- `http://127.0.0.1:8000/docs` lists the API endpoints.

### Empty database

- Dashboard shows the empty state.
- Health endpoint distinguishes “no devices” from “database unavailable”.
- Opening a non-existent device URL shows an API error, not a crashed page.

### Dashboard with recorded devices

- Device names, addresses and products are visible.
- Online/off/unknown badges match the recorder state.
- Current interval duration is plausible.
- Last snapshot age and query status are visible.
- Search and “only online” filtering work.
- Device cards open the detail page.

### Presence tab

- 24h, 7d, 30d and 90d range buttons refresh the data.
- Online/off timeline segments render.
- Open intervals are marked open.
- Intervals with `fully_observed=false` show the hatched observation-gap style.
- Uptime, online time, off time, sessions, found scans and longest-online values look plausible.
- Interval table matches the timeline.

### Current state tab

- Snapshot capture time, query status and coverage are visible.
- Missing ranges and errors are shown when present.
- Telemetry, firmware, module info, lifetime counters and today counters render.
- Configuration fields are readable and password fields show `***`.
- Calendar slots render.
- Daily statistics and event log tables render.
- A `current_tables` state source is visibly explained as a fallback.
- A device that is online but has an old snapshot shows the snapshot age instead of implying a live read.

### History tab

- Battery voltage and battery level charts render.
- Today counters chart renders.
- Daily consumption bars render.
- Config-change table renders, or shows “No config changes”.
- Changing the range refreshes charts.

### Snapshots tab

- Snapshot list is populated.
- Selecting a snapshot shows its parsed state.
- Snapshot with a missing EEPROM falls back to current tables and explains why.
- Compare selects only snapshots with stored EEPROM images.

### Compare tab

- Two snapshots can be selected and compared.
- Configuration, telemetry, counters and daily changes are shown.
- New and removed events are shown.
- Comparing the same snapshot or snapshots without EEPROM gives a useful message.

### Custom date range

- The device page has From/To datetime inputs and an Apply range button.
- Applying a valid custom range refreshes presence, history, snapshots and
  export.
- Preset buttons 24h/7d/30d/90d clear the custom range and fill the inputs.
- An empty or reversed custom range shows a validation message and does not
  reload data.
- The selected range label and export range reflect the custom range.

### Export tab

- Export uses the currently selected 24h/7d/30d/90d range.
- CSV with one dataset downloads a single `.csv`.
- CSV with multiple datasets downloads a `.zip` containing one CSV per
  selected dataset plus `metadata.json`.
- CSV delimiter options comma, semicolon and tab work.
- “UTF-8 BOM for CSV” adds a BOM when enabled.
- JSON export contains the selected datasets; “pretty JSON” controls
  indentation and “include metadata” controls the metadata object.
- XLSX export opens correctly and contains one sheet per selected dataset plus
  a metadata sheet when enabled.
- PDF export opens correctly, has a title, range, optional metadata and one
  section per dataset.
- PDF page size A4 and Letter work, and portrait/landscape orientation work.
- Metadata is included for JSON/XLSX/PDF and multi-dataset CSV ZIP exports. A
  single CSV contains only its dataset.
- Selecting no datasets shows an error and downloads nothing.
- An unknown dataset or invalid date range returns `422`.

### Recorder stopped

- Stop the recorder while the web app stays running.
- Health reports the recorder as stopped.
- Device state becomes unknown/stale rather than claiming a live online state.
- Existing history remains readable.

### Raw EEPROM

- With `raw_eeprom_download = false`, the download endpoint returns `403`.
- Do not enable raw download on an unauthenticated/exposed instance: the raw
  image contains password fields.

## 6. Authentication check

If `basic_auth_user` is configured, set the password in the environment and
provide it with `SSC_WEB_PASSWORD`:

```bash
SSC_WEB_PASSWORD='change-me' \
PYTHONPATH=. .venv/bin/python -m ssc.web \
    --config deploy/ssc-web.toml \
    --database /tmp/ssc-web-test.sqlite3
```

Without credentials the browser and `curl` should receive `401`.

## 7. Running under a different database permission setup

The web process uses `PRAGMA query_only=ON`, but SQLite WAL access can still
require write access to the database directory or `-shm` file. The simplest
local test is to run the web app as the same user as the recorder. For a
separate web user, follow the group/WAL permission notes in
`deploy/README.md`.

## 8. No automated tests

This project intentionally has no committed web test suite. Use the manual
checks above, preferably against a copy of a real recorder database and with
the recorder temporarily stopped to inspect stale/unknown states.