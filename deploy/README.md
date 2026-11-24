# Running the SSC recorder on Linux

The recorder is a long-running process that scans every 30 seconds. Devices
are discovered dynamically: no device list is required. The first time an SSC
device is seen, it is inserted into the SQLite database; a full state query is
performed only when the device transitions from offline to online. While the
device remains online, only presence samples are written.

## Host requirements

- Linux with BlueZ and D-Bus.
- A BLE adapter visible as `hci0` (or update `adapter` in the config).
- Python 3.12+ and a virtual environment.
- NTP/time synchronisation for accurate host timestamps.

```bash
sudo apt install bluez python3-venv
sudo systemctl enable --now bluetooth
bluetoothctl list
bluetoothctl show
```

Set `AutoEnable=true` in `/etc/bluetooth/main.conf` if the adapter should be
powered at boot. Place the host centrally relative to the devices, preferably
with an external USB BLE adapter on an extension cable away from USB 3 and
2.4 GHz Wi-Fi interference.

## Install

```bash
git clone <repository> /opt/schell-ssc-ble-client
cd /opt/schell-ssc-ble-client
python3 -m venv .venv
.venv/bin/pip install -e .

sudo useradd --system --home /var/lib/ssc-recorder \
    --shell /usr/sbin/nologin ssc-recorder
sudo usermod -aG bluetooth ssc-recorder

sudo install -d -o ssc-recorder -g ssc-recorder -m 0700 /var/lib/ssc-recorder
sudo install -d -o root -g ssc-recorder -m 0750 /etc/ssc-recorder
sudo install -m 0640 -o root -g ssc-recorder \
    deploy/recorder.toml /etc/ssc-recorder/recorder.toml
```

Test one cycle before enabling the service:

```bash
sudo -u ssc-recorder \
    /opt/schell-ssc-ble-client/.venv/bin/python \
    -m ssc.recorder --config /etc/ssc-recorder/recorder.toml --once
```

Inspect the recorded state:

```bash
sudo -u ssc-recorder \
    /opt/schell-ssc-ble-client/.venv/bin/python \
    -m ssc.recorder --config /etc/ssc-recorder/recorder.toml --status
```

## Running for testing (no full install)

The package is installed in editable ("dev") mode by `pip install -e .`, so any
change under `ssc/` is picked up live: no reinstall is needed. There is no
separate script to copy — the recorder is launched as a module through
`ssc/recorder/__main__.py`, which calls `main()` in `ssc/recorder/runner.py`.

From the repository root, without touching the system directories:

```bash
# Module form — the same path the systemd unit uses.
.venv/bin/python -m ssc.recorder --help

# The console script the editable install already created in the venv.
.venv/bin/ssc-recorder --help
```

The default config (`/etc/ssc-recorder/recorder.toml`) and database
(`/var/lib/ssc-recorder/ssc.sqlite3`) point at production paths that need root
and a real install. Override them for local testing:

```bash
# Dry run: scan and log SSC devices, no database writes at all.
.venv/bin/python -m ssc.recorder --dry-run --once --log-level DEBUG

# Real run, one cycle only, writing to a local database file.
.venv/bin/python -m ssc.recorder \
    --database ./ssc-test.sqlite3 --once --log-level DEBUG

# Inspect what was recorded in that local database.
.venv/bin/python -m ssc.recorder --database ./ssc-test.sqlite3 --status
```

Useful flags: `--once`, `--dry-run`, `--status`, `--database`, `--config`,
`--interval`, `--scan-duration`, `--adapter`, `--log-level`.

Notes:

- `--dry-run` skips the database entirely, so it is the safest first smoke test.
- Scans still need BLE adapter access via BlueZ/D-Bus; `--dry-run` does not
  bypass that.
- If the adapter is not `hci0`, pass `--adapter <name-or-address>`.

## systemd

```bash
sudo install -m 0644 deploy/ssc-recorder.service \
    /etc/systemd/system/ssc-recorder.service
sudo systemctl daemon-reload
sudo systemctl enable --now ssc-recorder
journalctl -u ssc-recorder -f
```

If BlueZ D-Bus access is denied, add a polkit/D-Bus policy for the
`ssc-recorder` user or grant the required capabilities. Running as root is the
simplest fallback but is not preferred.

## Important behaviour

- The recorder never keeps a BLE connection open between scans. It connects,
  queries, and disconnects immediately. This lets the devices power down when
  no other client is connected.
- A full query is done once per online period. A failed query is retried on
  following scans up to `max_query_attempts`.
- Scans that do not find a device do not create per-scan rows. The absence is
  represented by an `off_period` row; its duration is filled in when the device
  comes online again.
- The raw EEPROM image is deduplicated by SHA-256 and compressed. Parsed data is
  stored in separate tables with a timestamped `state_snapshot`.
- Full EEPROM dumps contain password fields. The database and backups should be
  owner-only. `redact_secrets` removes them from parsed config values, but the
  raw image still contains them.

## Web UI and API

The read-only web service runs separately from the recorder:

```bash
.venv/bin/pip install -e '.[web]'

sudo install -m 0640 -o root -g ssc-recorder \
    deploy/ssc-web.toml /etc/ssc-web.toml
sudo install -m 0644 deploy/ssc-web.service \
    /etc/systemd/system/ssc-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now ssc-web
journalctl -u ssc-web -f
```

The service binds to `127.0.0.1:8000`. Put nginx/Caddy with TLS and
authentication in front before exposing it beyond localhost. An example is in
`deploy/nginx-ssc.conf.example`.

The web process opens the recorder database with `PRAGMA query_only=ON` and
never writes to it. It runs as the recorder user in the example service so that
SQLite WAL and `-shm` access works. If you split the users, grant the web user
access to the database directory and WAL files.

If `basic_auth_user` is configured in `/etc/ssc-web.toml`, create
`/etc/ssc-web.env` with owner-only permissions and set
`SSC_WEB_PASSWORD=...` there. The service reads it through `EnvironmentFile`.
Prefer TLS and authentication at nginx/Caddy in front of the service.

### Testing the web app without installing it

See [`docs/WEB_TESTING.md`](../docs/WEB_TESTING.md) for source-run commands,
database-copy instructions, manual API checks and a browser test checklist.
No web test suite is committed.

## Backup

```bash
sudo install -d -o ssc-recorder -g ssc-recorder -m 0700 /var/backups/ssc
sqlite3 /var/lib/ssc-recorder/ssc.sqlite3 \
    ".backup '/var/backups/ssc/ssc-$(date +%F).sqlite3'"
```

Run this from a systemd timer or cron and keep the backup directory private.