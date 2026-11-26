/* SSC recorder dashboard frontend. */
(function () {
  "use strict";

  const ROOT = document.body.dataset.root || "";
  const PAGE = document.body.dataset.page || "";
  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function formatTime(value, fallback) {
    if (!value) return fallback || "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString("de-DE", {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  function formatShortTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString("de-DE", {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function formatDateOnly(value) {
    if (!value) return "—";
    const date = new Date(value + (String(value).length === 10 ? "T00:00:00" : ""));
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
    });
  }

  function formatDuration(seconds) {
    if (seconds == null || !isFinite(seconds)) return "—";
    const value = Math.max(0, Math.round(Number(seconds)));
    const days = Math.floor(value / 86400);
    const hours = Math.floor((value % 86400) / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const secs = value % 60;
    if (days) return `${days}d ${hours}h`;
    if (hours) return `${hours}h ${minutes}m`;
    if (minutes) return `${minutes}m ${secs}s`;
    return `${secs}s`;
  }

  function formatAge(seconds) {
    return seconds == null ? "—" : formatDuration(seconds) + " ago";
  }

  function num(value, digits) {
    if (value == null || value === "") return "—";
    const number = Number(value);
    if (!isFinite(number)) return String(value);
    return number.toLocaleString(undefined, {
      maximumFractionDigits: digits == null ? 2 : digits,
    });
  }

  function badge(state) {
    const kind = state === "online" || state === "off" ? state : "unknown";
    const label = kind === "online" ? "online" : kind === "off" ? "off" : "unknown";
    return `<span class="badge badge-${kind}">${label}</span>`;
  }

  function pill(value, kind) {
    return `<span class="pill ${escapeHtml(kind || "")}">${escapeHtml(value)}</span>`;
  }

  function metric(label, value) {
    return `<div class="metric"><span class="metric-label">${escapeHtml(
      label
    )}</span><span class="metric-value">${value}</span></div>`;
  }

  function showError(error) {
    const box = $("#global-error");
    if (!box) return;
    box.textContent = error instanceof Error ? error.message : String(error);
    box.classList.remove("hidden");
  }

  function clearError() {
    const box = $("#global-error");
    if (box) box.classList.add("hidden");
  }

  async function api(path) {
    const response = await fetch(`${ROOT}/api/v1${path}`, {
      headers: { Accept: "application/json" },
    });
    let body = null;
    try {
      body = await response.json();
    } catch (error) {
      body = null;
    }
    if (!response.ok) {
      const detail =
        body && body.detail
          ? body.detail
          : `${response.status} ${response.statusText}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return body;
  }

  async function loadHealth() {
    const badgeEl = $("#health-badge");
    try {
      const response = await fetch(`${ROOT}/api/v1/health`, {
        headers: { Accept: "application/json" },
      });
      let body = null;
      try {
        body = await response.json();
      } catch (error) {
        body = null;
      }
      if (!body) throw new Error("Health endpoint returned no JSON");
      const ok = body.status === "ok";
      if (badgeEl) {
        badgeEl.textContent = ok
          ? "healthy"
          : body.status === "degraded"
            ? "degraded"
            : "unavailable";
        badgeEl.className = `badge badge-${
          ok ? "online" : body.status === "degraded" ? "unknown" : "unknown"
        }`;
      }
      if (PAGE === "dashboard") {
        $("#health-recorder").textContent = body.recorder_running
          ? "running"
          : "stopped";
        $("#health-database").textContent = body.tables_ok
          ? `schema v${body.schema_version ?? "?"}`
          : "not ready";
        $("#health-last-scan").textContent = formatTime(body.latest_scan_at);
        $("#health-device-count").textContent = String(body.device_count ?? 0);
      }
      if (body.detail) showError(body.detail);
      return body;
    } catch (error) {
      if (badgeEl) {
        badgeEl.textContent = "unavailable";
        badgeEl.className = "badge badge-unknown";
      }
      showError(`Health check failed: ${error.message}`);
      return null;
    }
  }

  function renderDeviceCard(device) {
    const name = device.display_name || device.serial || device.address;
    const interval =
      device.current_interval_s == null
        ? "—"
        : formatDuration(device.current_interval_s);
    const snapshotAge = device.state_age_s == null ? "—" : formatAge(device.state_age_s);
    const battery =
      device.latest_battery_level == null
        ? "—"
        : `${device.latest_battery_level}%`;
    const href = `${ROOT}/devices/${device.id}`;
    return `<a class="device-card" href="${escapeHtml(href)}">
      <div class="device-card-head">
        <div>
          <h2>${escapeHtml(name)}</h2>
          <div class="device-address">${escapeHtml(device.address)}</div>
        </div>
        ${badge(device.state)}
      </div>
      <div class="muted">${escapeHtml(device.product || device.identifier || "")}</div>
      <div class="device-metrics">
        ${metric("Current interval", escapeHtml(interval))}
        ${metric("Last snapshot", escapeHtml(snapshotAge))}
        ${metric("Battery", escapeHtml(battery))}
        ${metric("Query", escapeHtml(device.latest_query_status || "—"))}
      </div>
    </a>`;
  }

  async function loadDevices() {
    clearError();
    try {
      const onlineOnly = $("#online-only") && $("#online-only").checked;
      const search = $("#device-search") ? $("#device-search").value.trim() : "";
      const params = new URLSearchParams();
      if (onlineOnly) params.set("online_only", "true");
      if (search) params.set("search", search);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      const devices = await api(`/devices${suffix}`);
      const grid = $("#device-grid");
      const empty = $("#empty-state");
      if (!devices.length) {
        grid.innerHTML = "";
        empty.classList.remove("hidden");
        return;
      }
      empty.classList.add("hidden");
      grid.innerHTML = devices.map(renderDeviceCard).join("");
    } catch (error) {
      showError(error);
    }
  }

  function initDashboard() {
    loadHealth();
    loadDevices();
    const refresh = $("#refresh-devices");
    if (refresh) refresh.addEventListener("click", loadDevices);
    const search = $("#device-search");
    if (search) {
      search.addEventListener("input", () => {
        window.clearTimeout(search._timer);
        search._timer = window.setTimeout(loadDevices, 250);
      });
    }
    const onlineOnly = $("#online-only");
    if (onlineOnly) onlineOnly.addEventListener("change", loadDevices);
  }

  const device = {
    id: Number(document.body.dataset.deviceId || 0),
    rangeDays: 30,
    customRange: null,
    snapshots: [],
    loading: false,
  };

  function rangeParams() {
    if (device.customRange) return { ...device.customRange };
    const to = new Date();
    const from = new Date(to.getTime() - device.rangeDays * 86400000);
    return { from: from.toISOString(), to: to.toISOString() };
  }

  function localInputValue(value) {
    const date = new Date(value);
    const pad = (part) => String(part).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
      date.getDate()
    )}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function fillRangeInputs(from, to) {
    const fromInput = $("#range-from");
    const toInput = $("#range-to");
    if (fromInput) fromInput.value = localInputValue(from);
    if (toInput) toInput.value = localInputValue(to);
  }

  function rangeDescription() {
    if (device.customRange) {
      return `custom ${formatShortTime(device.customRange.from)} → ${formatShortTime(
        device.customRange.to
      )}`;
    }
    return `last ${device.rangeDays} day(s)`;
  }

  function rangeQuery(extra) {
    const range = rangeParams();
    const params = new URLSearchParams({ from: range.from, to: range.to });
    Object.entries(extra || {}).forEach(([key, value]) => {
      if (value != null && value !== "") params.set(key, value);
    });
    return params.toString();
  }

  function renderDeviceHeader(data) {
    const name = data.display_name || data.serial || data.address;
    $("#device-title").textContent = name;
    $("#device-address").textContent = data.address;
    $("#device-product").textContent = [data.product, data.serial]
      .filter(Boolean)
      .join(" · ");
    const badgeEl = $("#device-state");
    badgeEl.outerHTML = badge(data.state).replace(
      'class="badge',
      'id="device-state" class="badge'
    );
    const summary = $("#device-summary");
    summary.innerHTML = [
      metric("State", badge(data.state)),
      metric(
        "Current interval",
        escapeHtml(formatDuration(data.current_interval_s))
      ),
      metric("Last seen", escapeHtml(formatTime(data.last_seen_at))),
      metric("Last snapshot", escapeHtml(formatAge(data.state_age_s))),
      metric(
        "Battery",
        escapeHtml(
          data.latest_battery_level == null
            ? "—"
            : `${data.latest_battery_level}% (${num(data.latest_battery_voltage_v, 2)} V)`
        )
      ),
      metric("Query", escapeHtml(data.latest_query_status || "—")),
    ].join("");
    if (!data.recorder_running) {
      showError(
        "The recorder is not currently running; online/off state is unknown and may be stale."
      );
    }
  }

  async function loadDevice() {
    try {
      const data = await api(`/devices/${device.id}`);
      renderDeviceHeader(data);
    } catch (error) {
      showError(error);
    }
  }

  function renderPresence(data) {
    const summary = data.summary || {};
    $("#presence-summary").innerHTML = [
      metric("Uptime", `${num(summary.uptime_pct, 1)}%`),
      metric("Online time", escapeHtml(formatDuration(summary.online_s))),
      metric("Off time", escapeHtml(formatDuration(summary.off_s))),
      metric("Sessions", num(summary.sessions, 0)),
      metric("Found scans", num(summary.found_samples, 0)),
      metric("Longest online", escapeHtml(formatDuration(summary.longest_online_s))),
    ].join("");

    const timeline = $("#presence-timeline");
    timeline.innerHTML = "";
    const from = new Date(data.from || data.from_at).getTime();
    const to = new Date(data.to || data.to_at).getTime();
    const now = new Date(data.now || Date.now()).getTime();
    const total = Math.max(1, to - from);
    (data.intervals || []).forEach((interval) => {
      const start = Math.max(from, new Date(interval.started_at).getTime());
      const end = Math.min(
        to,
        interval.ended_at ? new Date(interval.ended_at).getTime() : now
      );
      if (!isFinite(start) || !isFinite(end) || end <= start) return;
      const segment = document.createElement("div");
      segment.className = `presence-segment ${interval.kind}`;
      if (!interval.fully_observed) segment.classList.add("gap");
      segment.style.left = `${((start - from) / total) * 100}%`;
      segment.style.width = `${Math.max(0.15, ((end - start) / total) * 100)}%`;
      segment.title = `${interval.kind} · ${formatDuration(interval.duration_s)}${
        interval.fully_observed ? "" : " · observation gap"
      }`;
      timeline.appendChild(segment);
    });
    if (!timeline.children.length) {
      timeline.innerHTML =
        '<div class="muted" style="padding:20px">No intervals in this range.</div>';
    }
    const scale = document.createElement("div");
    scale.className = "presence-scale";
    scale.innerHTML = `<span>${escapeHtml(formatShortTime(new Date(from)))}</span>
      <span>${escapeHtml(formatShortTime(new Date(to)))}</span>`;
    timeline.appendChild(scale);

    const tbody = $("#presence-table tbody");
    tbody.innerHTML = (data.intervals || [])
      .map(
        (interval) => `<tr>
          <td>${badge(interval.kind)}</td>
          <td>${escapeHtml(formatTime(interval.started_at))}</td>
          <td>${escapeHtml(formatTime(interval.ended_at))}</td>
          <td class="num">${escapeHtml(formatDuration(interval.duration_s))}</td>
          <td>${interval.open ? "yes" : "no"}</td>
          <td>${interval.fully_observed ? "yes" : "approx."}</td>
          <td>${escapeHtml(interval.query_status || "—")}</td>
        </tr>`
      )
      .join("");
    if (!tbody.children.length) {
      tbody.innerHTML =
        '<tr><td colspan="7" class="muted">No intervals in this range.</td></tr>';
    }
  }

  async function loadPresence() {
    try {
      const data = await api(
        `/devices/${device.id}/presence?${rangeQuery({ limit: 5000 })}`
      );
      renderPresence(data);
    } catch (error) {
      showError(error);
    }
  }

  function kvGrid(items) {
    return `<div class="kv">${items
      .map(
        ([label, value]) =>
          `<div><span>${escapeHtml(label)}</span>${escapeHtml(value)}</div>`
      )
      .join("")}</div>`;
  }

  function section(title, body, subtitle) {
    return `<div class="card">
      <div class="card-head"><h2>${escapeHtml(title)}</h2>${
        subtitle ? `<span class="muted">${escapeHtml(subtitle)}</span>` : ""
      }</div>
      ${body}
    </div>`;
  }

  function configValue(field) {
    if (field.value_type === "redacted") return "***";
    if (field.value_bool != null) return field.value_bool ? "true" : "false";
    if (field.value_text != null) return field.value_text;
    if (field.value_number != null) return String(field.value_number);
    return "—";
  }

  function renderState(container, state) {
    if (!state || !state.snapshot) {
      container.innerHTML = `<div class="empty">
        <h2>No state snapshot yet</h2>
        <p>The recorder has not stored a parsed state for this device.</p>
      </div>`;
      return;
    }
    const snapshot = state.snapshot;
    const status = snapshot.query_status || "unknown";
    const meta = [
      pill(`captured ${formatTime(snapshot.captured_at)}`),
      pill(status, status),
      pill(`coverage ${num(snapshot.coverage, 0)} bytes`),
      pill(`source ${state.state_source || "—"}`),
    ];
    if (snapshot.completed_at) {
      meta.push(pill(`completed ${formatTime(snapshot.completed_at)}`));
    }
    if (snapshot.device_datetime) {
      meta.push(pill(`device time ${formatTime(snapshot.device_datetime)}`));
    }
    if (snapshot.missing_ranges && snapshot.missing_ranges.length) {
      meta.push(pill(`${snapshot.missing_ranges.length} missing range(s)`, "partial"));
    }
    if (snapshot.error) meta.push(pill(`error: ${snapshot.error}`, "failed"));

    const parts = [];
    parts.push(
      section(
        "Snapshot",
        `<div class="snapshot-meta">${meta.join("")}</div>
         ${
           state.state_source === "current_tables"
             ? '<p class="muted">The raw EEPROM image is unavailable for this snapshot; parsed config/calendar/daily/events come from the latest current-value tables.</p>'
             : ""
         }`
      )
    );

    if (state.telemetry) {
      parts.push(
        section(
          "Telemetry",
          kvGrid([
            ["Battery level", `${num(state.telemetry.battery_level, 0)}%`],
            ["Battery voltage", `${num(state.telemetry.battery_voltage_v, 2)} V`],
            ["VCC", `${num(state.telemetry.vcc_v, 3)} V`],
            ["3.3 V rail raw", num(state.telemetry.rail_33_raw, 0)],
            ["Temperature raw", num(state.telemetry.temperature_raw, 0)],
            ["Device time", formatTime(state.telemetry.device_datetime)],
          ])
        )
      );
    }

    const systemItems = [];
    if (state.firmware) {
      systemItems.push(["Hardware", state.firmware.hardware_version || "—"]);
      systemItems.push(["Bootloader", state.firmware.bootloader_version || "—"]);
      systemItems.push(["Reset reason", state.firmware.reset_reason || "—"]);
    }
    if (state.module_info) {
      systemItems.push(["App version", state.module_info.app_version || "—"]);
      systemItems.push(["Serial", state.module_info.serial || "—"]);
    }
    if (state.lifetime) {
      systemItems.push(["Restarts", num(state.lifetime.count_restart, 0)]);
      systemItems.push(["Lifetime count", num(state.lifetime.count_lifetime, 0)]);
    }
    if (state.today) {
      systemItems.push(["Today count", num(state.today.count_normal, 0)]);
      systemItems.push(["Today runtime", `${num(state.today.runtime_normal, 0)} min`]);
      systemItems.push([
        "Today consumption",
        `${num(state.today.consumption_normal_l, 2)} L`,
      ]);
    }
    if (systemItems.length) parts.push(section("System", kvGrid(systemItems)));

    container.innerHTML = parts.join("") + stateDetails(state);
  }

  function stateDetails(state) {
    const parts = [];

    if (state.config && state.config.length) {
      const rows = state.config
        .map((field) => {
          const name = field.name.replace(/^EEPROM_/, "");
          return `<tr>
            <td>${escapeHtml(name)}</td>
            <td class="mono">${escapeHtml(configValue(field))}</td>
            <td>${escapeHtml(field.value_type)}</td>
            <td>${escapeHtml(formatTime(field.last_seen_at))}</td>
          </tr>`;
        })
        .join("");
      parts.push(
        section(
          "Configuration",
          `<div class="table-wrap"><table>
            <thead><tr><th>Field</th><th>Value</th><th>Type</th><th>Last seen</th></tr></thead>
            <tbody>${rows}</tbody>
          </table></div>`
        )
      );
    }

    if (state.calendar && state.calendar.length) {
      const rows = state.calendar
        .map(
          (slot) => `<tr>
            <td>${slot.slot_index}</td>
            <td>${escapeHtml(slot.mode)}</td>
            <td>${escapeHtml(slot.days || "—")}</td>
            <td>${String(slot.hour).padStart(2, "0")}:${String(slot.minute).padStart(
              2,
              "0"
            )}:${String(slot.second).padStart(2, "0")}</td>
            <td class="num">${escapeHtml(formatDuration(slot.runtime_s))}</td>
          </tr>`
        )
        .join("");
      parts.push(
        section(
          "Calendar",
          `<div class="table-wrap"><table>
            <thead><tr><th>Slot</th><th>Mode</th><th>Days</th><th>Time</th><th>Runtime</th></tr></thead>
            <tbody>${rows}</tbody>
          </table></div>`
        )
      );
    }

    if (state.daily_stats && state.daily_stats.length) {
      const rows = state.daily_stats
        .slice(-30)
        .reverse()
        .map(
          (day) => `<tr>
            <td>${escapeHtml(formatDateOnly(day.date))}</td>
            <td class="num">${num(day.count_normal, 0)}</td>
            <td class="num">${num(day.runtime_normal, 0)}</td>
            <td class="num">${num(day.consumption_normal_l, 2)}</td>
            <td class="num">${num(day.count_stagnation, 0)}</td>
          </tr>`
        )
        .join("");
      parts.push(
        section(
          "Daily statistics",
          `<div class="table-wrap"><table>
            <thead><tr><th>Date</th><th>Count</th><th>Runtime</th><th>Litres</th><th>Stagnation</th></tr></thead>
            <tbody>${rows}</tbody>
          </table></div>`,
          "latest 30 days"
        )
      );
    }

    if (state.events && state.events.length) {
      const rows = state.events
        .slice(-30)
        .reverse()
        .map(
          (event) => `<tr>
            <td>${escapeHtml(formatTime(event.occurred_at))}</td>
            <td>${escapeHtml(event.log_type)}</td>
            <td>${escapeHtml(event.status || "—")}</td>
            <td class="num">${escapeHtml(formatDuration(event.duration_s))}</td>
          </tr>`
        )
        .join("");
      parts.push(
        section(
          "Event log",
          `<div class="table-wrap"><table>
            <thead><tr><th>Occurred</th><th>Log</th><th>Status</th><th>Duration</th></tr></thead>
            <tbody>${rows}</tbody>
          </table></div>`,
          "latest 30 events"
        )
      );
    }

    return parts.join("");
  }

  async function loadCurrent() {
    try {
      const state = await api(`/devices/${device.id}/state/current`);
      renderState($("#current-state"), state);
    } catch (error) {
      showError(error);
    }
  }

  function linePoints(points, key) {
    return (points || [])
      .map((point) => ({
        x: new Date(point.captured_at).getTime(),
        y: point[key],
      }))
      .filter((point) => isFinite(point.x) && isFinite(point.y));
  }

  function renderHistory(telemetry, counters, daily, changes) {
    const charts = window.SSCCharts;
    charts.line($("#battery-voltage-chart"), [
      {
        label: "battery voltage",
        color: "#2563eb",
        points: linePoints(telemetry.points, "battery_voltage_v"),
      },
    ]);
    charts.line($("#battery-level-chart"), [
      {
        label: "battery level",
        color: "#12805c",
        points: linePoints(telemetry.points, "battery_level"),
      },
    ]);
    charts.line($("#counter-chart"), [
      {
        label: "count normal",
        color: "#2563eb",
        points: linePoints(counters.points, "count_normal"),
      },
      {
        label: "count stagnation",
        color: "#b45309",
        points: linePoints(counters.points, "count_stagnation"),
      },
    ]);
    const dailyItems = (daily.items || []).slice(-30);
    charts.bars(
      $("#daily-chart"),
      dailyItems.map((item) => String(item.date).slice(5)),
      dailyItems.map((item) => item.consumption_normal_l || 0),
      { color: "#7c3aed" }
    );

    const tbody = $("#config-change-table tbody");
    tbody.innerHTML = (changes.items || [])
      .map(
        (change) => `<tr>
          <td>${escapeHtml(formatTime(change.changed_at))}</td>
          <td>${escapeHtml(change.name.replace(/^EEPROM_/, ""))}</td>
          <td class="mono">${escapeHtml(change.old_value_text ?? "—")}</td>
          <td class="mono">${escapeHtml(change.new_value_text ?? "—")}</td>
        </tr>`
      )
      .join("");
    if (!tbody.children.length) {
      tbody.innerHTML =
        '<tr><td colspan="4" class="muted">No config changes in this range.</td></tr>';
    }
  }

  async function loadHistory() {
    try {
      const range = rangeParams();
      const dailyFrom = range.from.slice(0, 10);
      const dailyTo = range.to.slice(0, 10);
      const [telemetry, counters, daily, changes] = await Promise.all([
        api(`/devices/${device.id}/history/telemetry?${rangeQuery({ bucket: "day" })}`),
        api(`/devices/${device.id}/history/counters?${rangeQuery()}`),
        api(`/devices/${device.id}/history/daily?from=${dailyFrom}&to=${dailyTo}`),
        api(`/devices/${device.id}/history/config-changes?${rangeQuery({ limit: 200 })}`),
      ]);
      renderHistory(telemetry, counters, daily, changes);
    } catch (error) {
      showError(error);
    }
  }

  function snapshotLabel(snapshot) {
    return `${formatShortTime(snapshot.captured_at)} · ${snapshot.query_status} · ${num(
      snapshot.coverage,
      0
    )} bytes`;
  }

  function renderSnapshotList(data) {
    const list = $("#snapshot-list");
    $("#snapshot-count").textContent = `${data.total} snapshot(s)`;
    list.innerHTML = "";
    if (!data.items.length) {
      list.innerHTML = '<p class="muted">No snapshots recorded.</p>';
    }
    data.items.forEach((snapshot) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "snapshot-item";
      button.innerHTML = `<span><strong>${escapeHtml(
        formatTime(snapshot.captured_at)
      )}</strong><br><span class="muted">${escapeHtml(
        snapshotLabel(snapshot)
      )}</span></span><span>${pill(
        snapshot.query_status,
        snapshot.query_status
      )}</span>`;
      button.addEventListener("click", () => openSnapshot(snapshot.id, button));
      list.appendChild(button);
    });

    const options = data.items
      .filter((snapshot) => snapshot.eeprom)
      .map(
        (snapshot) =>
          `<option value="${snapshot.id}">${escapeHtml(
            formatTime(snapshot.captured_at)
          )}</option>`
      )
      .join("");
    ["#compare-base", "#compare-target"].forEach((selector) => {
      const select = $(selector);
      select.innerHTML = options || '<option value="">no EEPROM snapshots</option>';
    });
    const base = $("#compare-base");
    const target = $("#compare-target");
    if (base && target && base.options.length > 1) {
      target.selectedIndex = 0;
      base.selectedIndex = Math.min(1, base.options.length - 1);
    }
  }

  async function loadSnapshots() {
    try {
      const data = await api(
        `/devices/${device.id}/snapshots?${rangeQuery({ limit: 100 })}`
      );
      device.snapshots = data.items || [];
      renderSnapshotList(data);
    } catch (error) {
      showError(error);
    }
  }

  async function openSnapshot(snapshotId, button) {
    $$(".snapshot-item").forEach((item) => item.classList.remove("active"));
    if (button) button.classList.add("active");
    const detail = $("#snapshot-detail");
    detail.innerHTML = '<p class="muted">Loading snapshot…</p>';
    try {
      const state = await api(`/devices/${device.id}/snapshots/${snapshotId}`);
      renderState(detail, state);
    } catch (error) {
      detail.innerHTML = `<p class="alert alert-error">${escapeHtml(error.message)}</p>`;
    }
  }

  function compareTable(rows, columns) {
    if (!rows.length) return '<p class="muted">No changes.</p>';
    const head = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
    const body = rows
      .map(
        (row) =>
          `<tr>${columns
            .map((column) => `<td>${escapeHtml(row[column] ?? "—")}</td>`)
            .join("")}</tr>`
      )
      .join("");
    return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function renderCompare(result) {
    const configRows = (result.config_changes || []).map((change) => ({
      Field: change.name.replace(/^EEPROM_/, ""),
      Base: change.base_value ?? "—",
      Target: change.target_value ?? "—",
    }));
    const telemetryRows = Object.entries(result.telemetry_changes || {}).map(
      ([field, change]) => ({
        Field: field,
        Base: change.base ?? "—",
        Target: change.target ?? "—",
      })
    );
    const counterRows = Object.entries(result.counter_changes || {}).map(
      ([field, change]) => ({
        Field: field,
        Base: change.base ?? "—",
        Target: change.target ?? "—",
      })
    );
    const dailyRows = (result.daily_changes || []).flatMap((day) =>
      Object.entries(day.changes || {}).map(([field, change]) => ({
        Date: day.date,
        Field: field,
        Base: change.base ?? "—",
        Target: change.target ?? "—",
      }))
    );
    const newEvents = (result.new_events || []).map((event) => ({
      Occurred: formatTime(event.occurred_at),
      Log: event.log_type,
      Status: event.status || "—",
      Duration: formatDuration(event.duration_s),
    }));
    const removedEvents = (result.removed_events || []).map((event) => ({
      Occurred: formatTime(event.occurred_at),
      Log: event.log_type,
      Status: event.status || "—",
      Duration: formatDuration(event.duration_s),
    }));
    $("#compare-result").innerHTML = `
      <div class="compare-group"><h3>Configuration</h3>${compareTable(
        configRows,
        ["Field", "Base", "Target"]
      )}</div>
      <div class="compare-group"><h3>Telemetry</h3>${compareTable(
        telemetryRows,
        ["Field", "Base", "Target"]
      )}</div>
      <div class="compare-group"><h3>Counters</h3>${compareTable(
        counterRows,
        ["Field", "Base", "Target"]
      )}</div>
      <div class="compare-group"><h3>Daily statistics</h3>${compareTable(
        dailyRows,
        ["Date", "Field", "Base", "Target"]
      )}</div>
      <div class="compare-group"><h3>New events</h3>${compareTable(
        newEvents,
        ["Occurred", "Log", "Status", "Duration"]
      )}</div>
      <div class="compare-group"><h3>Removed events</h3>${compareTable(
        removedEvents,
        ["Occurred", "Log", "Status", "Duration"]
      )}</div>`;
  }

  async function runCompare() {
    const base = $("#compare-base").value;
    const target = $("#compare-target").value;
    if (!base || !target) {
      showError("No comparable snapshots with EEPROM images are available.");
      return;
    }
    if (base === target) {
      showError("Choose two different snapshots.");
      return;
    }
    $("#compare-result").innerHTML = '<p class="muted">Comparing…</p>';
    try {
      const result = await api(
        `/devices/${device.id}/compare?base=${encodeURIComponent(
          base
        )}&target=${encodeURIComponent(target)}`
      );
      renderCompare(result);
    } catch (error) {
      $("#compare-result").innerHTML = `<p class="alert alert-error">${escapeHtml(
        error.message
      )}</p>`;
    }
  }

  function updateExportRange() {
    const label = $("#export-range");
    if (label) label.textContent = rangeDescription();
  }

  function selectedExportDatasets() {
    return $$(".export-dataset:checked").map((input) => input.value);
  }

  function syncSelectAll() {
    const all = $("#export-select-all");
    const boxes = $$(".export-dataset");
    if (!all) return;
    all.checked = boxes.length > 0 && boxes.every((box) => box.checked);
  }

  function syncExportFormat() {
    const format = $("#export-format") ? $("#export-format").value : "csv";
    const delimiter = $("#export-delimiter");
    const bom = $("#export-bom");
    const pretty = $("#export-pretty");
    const pdfPage = $("#export-pdf-page");
    const pdfOrientation = $("#export-pdf-orientation");
    if (delimiter) delimiter.disabled = format !== "csv";
    if (bom) bom.disabled = format !== "csv";
    if (pretty) pretty.disabled = format !== "json";
    if (pdfPage) pdfPage.disabled = format !== "pdf";
    if (pdfOrientation) pdfOrientation.disabled = format !== "pdf";
  }

  async function downloadExport(event) {
    event.preventDefault();
    clearError();
    const datasets = selectedExportDatasets();
    const status = $("#export-status");
    if (!datasets.length) {
      if (status) status.textContent = "Select at least one dataset.";
      return;
    }
    const format = $("#export-format").value;
    const params = new URLSearchParams({
      format,
      datasets: datasets.join(","),
      delimiter: $("#export-delimiter").value,
      pretty: $("#export-pretty").checked ? "true" : "false",
      include_metadata: $("#export-metadata").checked ? "true" : "false",
      bom: $("#export-bom").checked ? "true" : "false",
      pdf_page_size: $("#export-pdf-page").value,
      pdf_orientation: $("#export-pdf-orientation").value,
    });
    const range = rangeParams();
    params.set("from", range.from);
    params.set("to", range.to);
    if (status) status.textContent = "Preparing export…";
    try {
      const response = await fetch(
        `${ROOT}/api/v1/devices/${device.id}/export?${params.toString()}`,
        { headers: { Accept: "*/*" } }
      );
      if (!response.ok) {
        let detail = `${response.status} ${response.statusText}`;
        try {
          const body = await response.json();
          if (body && body.detail) detail = body.detail;
        } catch (error) {
          // The response was not JSON.
        }
        throw new Error(detail);
      }
      const blob = await response.blob();
      const disposition = response.headers.get("content-disposition") || "";
      const match = disposition.match(/filename="?([^";]+)"?/i);
      const filename = match ? match[1] : `ssc-export.${format}`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      if (status) status.textContent = `Downloaded ${filename}`;
    } catch (error) {
      if (status) status.textContent = "";
      showError(error);
    }
  }

  function setTab(name) {
    $$(".tabs button").forEach((button) => {
      button.classList.toggle("active", button.dataset.tab === name);
    });
    $$(".tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.panel === name);
    });
  }

  function setRange(days) {
    device.rangeDays = days;
    device.customRange = null;
    $$("[data-range]").forEach((button) => {
      button.classList.toggle("active", Number(button.dataset.range) === days);
    });
    const range = rangeParams();
    fillRangeInputs(range.from, range.to);
    const label = $("#range-label");
    if (label) label.textContent = rangeDescription();
    updateExportRange();
    loadPresence();
    loadHistory();
    loadSnapshots();
  }

  function applyCustomRange() {
    const fromValue = $("#range-from") ? $("#range-from").value : "";
    const toValue = $("#range-to") ? $("#range-to").value : "";
    if (!fromValue || !toValue) {
      showError("Choose both a start and an end for the custom range.");
      return;
    }
    const from = new Date(fromValue);
    const to = new Date(toValue);
    if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) {
      showError("The custom range contains an invalid date.");
      return;
    }
    if (from >= to) {
      showError("The custom range start must be before the end.");
      return;
    }
    clearError();
    device.customRange = {
      from: from.toISOString(),
      to: to.toISOString(),
    };
    $$("[data-range]").forEach((button) => button.classList.remove("active"));
    const label = $("#range-label");
    if (label) label.textContent = rangeDescription();
    updateExportRange();
    loadPresence();
    loadHistory();
    loadSnapshots();
  }

  function initDevicePage() {
    loadHealth();
    loadDevice();
    loadCurrent();

    $$(".tabs button").forEach((button) => {
      button.addEventListener("click", () => {
        setTab(button.dataset.tab);
        if (button.dataset.tab === "history") loadHistory();
        if (button.dataset.tab === "snapshots") loadSnapshots();
        if (button.dataset.tab === "export") updateExportRange();
      });
    });
    $$("[data-range]").forEach((button) => {
      button.addEventListener("click", () => setRange(Number(button.dataset.range)));
    });
    const applyRange = $("#apply-range");
    if (applyRange) applyRange.addEventListener("click", applyCustomRange);
    const refresh = $("#refresh-device");
    if (refresh) {
      refresh.addEventListener("click", () => {
        clearError();
        loadDevice();
        loadPresence();
        loadCurrent();
        loadHistory();
        loadSnapshots();
      });
    }
    const compare = $("#compare-button");
    if (compare) compare.addEventListener("click", runCompare);
    const exportForm = $("#export-form");
    if (exportForm) exportForm.addEventListener("submit", downloadExport);
    const exportFormat = $("#export-format");
    if (exportFormat) exportFormat.addEventListener("change", syncExportFormat);
    syncExportFormat();
    const selectAll = $("#export-select-all");
    if (selectAll) {
      selectAll.addEventListener("change", () => {
        $$(".export-dataset").forEach((box) => {
          box.checked = selectAll.checked;
        });
      });
    }
    $$(".export-dataset").forEach((box) => {
      box.addEventListener("change", syncSelectAll);
    });
    setRange(device.rangeDays);
  }

  if (PAGE === "dashboard") {
    initDashboard();
  } else if (PAGE === "device") {
    initDevicePage();
  }

  window.setInterval(() => {
    if (document.hidden) return;
    loadHealth();
    if (PAGE === "dashboard") {
      loadDevices();
    } else if (PAGE === "device") {
      loadDevice();
      const active = $(".tab-panel.active");
      if (active && active.dataset.panel === "presence") loadPresence();
      if (active && active.dataset.panel === "current") loadCurrent();
    }
  }, 30000);
})();