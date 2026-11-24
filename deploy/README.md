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

## Backup

```bash
sudo install -d -o ssc-recorder -g ssc-recorder -m 0700 /var/backups/ssc
sqlite3 /var/lib/ssc-recorder/ssc.sqlite3 \
    ".backup '/var/backups/ssc/ssc-$(date +%F).sqlite3'"
```

Run this from a systemd timer or cron and keep the backup directory private.