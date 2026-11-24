/* Minimal dependency-free canvas charts for the SSC dashboard. */
(function () {
  "use strict";

  const PALETTE = ["#2563eb", "#12805c", "#b45309", "#7c3aed", "#b42318"];

  function setup(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const cssWidth = canvas.clientWidth || canvas.parentElement.clientWidth || 600;
    const cssHeight = Number(canvas.getAttribute("height") || 220);
    canvas.width = Math.max(1, Math.floor(cssWidth * dpr));
    canvas.height = Math.max(1, Math.floor(cssHeight * dpr));
    canvas.style.height = cssHeight + "px";
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width: cssWidth, height: cssHeight };
  }

  function css(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return value ? value.trim() : fallback;
  }

  function empty(canvas, message) {
    const { ctx, width, height } = setup(canvas);
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = css("--muted", "#667085");
    ctx.font = "13px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(message, width / 2, height / 2);
  }

  function niceRange(min, max) {
    if (!isFinite(min) || !isFinite(max)) return { min: 0, max: 1 };
    if (min === max) {
      const pad = Math.abs(min) * 0.1 || 1;
      return { min: min - pad, max: max + pad };
    }
    const pad = (max - min) * 0.08;
    return { min: min - pad, max: max + pad };
  }

  function formatNumber(value) {
    if (value == null || !isFinite(value)) return "—";
    const abs = Math.abs(value);
    if (abs >= 1000) return Math.round(value).toLocaleString();
    if (abs >= 10) return value.toFixed(1);
    if (abs >= 1) return value.toFixed(2);
    return value.toFixed(3);
  }

  function formatDate(ms, detailed) {
    const date = new Date(ms);
    if (Number.isNaN(date.getTime())) return "";
    const options = detailed
      ? { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }
      : { month: "short", day: "2-digit" };
    return date.toLocaleString(undefined, options);
  }

  function line(canvas, series, options) {
    const clean = (series || [])
      .map((item) => ({
        label: item.label,
        color: item.color,
        points: (item.points || []).filter(
          (p) => p && isFinite(p.y) && p.x != null
        ),
      }))
      .filter((item) => item.points.length);
    if (!clean.length) {
      empty(canvas, "No data in the selected range");
      return;
    }

    const { ctx, width, height } = setup(canvas);
    ctx.clearRect(0, 0, width, height);
    const pad = { left: 52, right: 14, top: 28, bottom: 28 };
    const plotW = Math.max(1, width - pad.left - pad.right);
    const plotH = Math.max(1, height - pad.top - pad.bottom);

    const xs = clean.flatMap((item) => item.points.map((p) => p.x));
    const ys = clean.flatMap((item) => item.points.map((p) => p.y));
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    const yRange = niceRange(Math.min(...ys), Math.max(...ys));
    const xSpan = xMax - xMin || 1;
    const x = (value) => pad.left + ((value - xMin) / xSpan) * plotW;
    const y = (value) =>
      pad.top + plotH - ((value - yRange.min) / (yRange.max - yRange.min)) * plotH;

    ctx.strokeStyle = css("--border", "#d9dee6");
    ctx.fillStyle = css("--muted", "#667085");
    ctx.lineWidth = 1;
    ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let i = 0; i <= 4; i += 1) {
      const value = yRange.min + ((yRange.max - yRange.min) * i) / 4;
      const py = y(value);
      ctx.beginPath();
      ctx.moveTo(pad.left, py);
      ctx.lineTo(width - pad.right, py);
      ctx.stroke();
      ctx.fillText(formatNumber(value), pad.left - 8, py);
    }

    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(formatDate(xMin, true), pad.left, height - pad.bottom + 8);
    ctx.textAlign = "right";
    ctx.fillText(formatDate(xMax, true), width - pad.right, height - pad.bottom + 8);

    clean.forEach((item, index) => {
      const color = item.color || PALETTE[index % PALETTE.length];
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      item.points
        .slice()
        .sort((a, b) => a.x - b.x)
        .forEach((point, pointIndex) => {
          const px = x(point.x);
          const py = y(point.y);
          if (pointIndex === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        });
      ctx.stroke();
      if (item.points.length <= 150) {
        ctx.fillStyle = color;
        item.points.forEach((point) => {
          ctx.beginPath();
          ctx.arc(x(point.x), y(point.y), 2.2, 0, Math.PI * 2);
          ctx.fill();
        });
      }
    });

    let legendX = pad.left;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    clean.forEach((item, index) => {
      const color = item.color || PALETTE[index % PALETTE.length];
      ctx.fillStyle = color;
      ctx.fillRect(legendX, 8, 10, 3);
      ctx.fillStyle = css("--muted", "#667085");
      ctx.fillText(item.label, legendX + 15, 10);
      legendX += ctx.measureText(item.label).width + 42;
    });
  }

  function bars(canvas, labels, values, options) {
    const points = (values || []).map(Number);
    if (!points.length) {
      empty(canvas, "No data in the selected range");
      return;
    }
    const { ctx, width, height } = setup(canvas);
    ctx.clearRect(0, 0, width, height);
    const pad = { left: 52, right: 14, top: 24, bottom: 34 };
    const plotW = Math.max(1, width - pad.left - pad.right);
    const plotH = Math.max(1, height - pad.top - pad.bottom);
    const yRange = niceRange(0, Math.max(...points));
    const step = plotW / points.length;
    const barW = Math.max(1, Math.min(18, step * 0.7));
    const color = (options && options.color) || PALETTE[0];

    ctx.strokeStyle = css("--border", "#d9dee6");
    ctx.fillStyle = css("--muted", "#667085");
    ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let i = 0; i <= 4; i += 1) {
      const value = (yRange.max * i) / 4;
      const py = pad.top + plotH - (value / yRange.max) * plotH;
      ctx.beginPath();
      ctx.moveTo(pad.left, py);
      ctx.lineTo(width - pad.right, py);
      ctx.stroke();
      ctx.fillText(formatNumber(value), pad.left - 8, py);
    }

    points.forEach((value, index) => {
      const px = pad.left + index * step + (step - barW) / 2;
      const barH = (value / yRange.max) * plotH;
      ctx.fillStyle = color;
      ctx.fillRect(px, pad.top + plotH - barH, barW, barH);
    });

    const stride = Math.max(1, Math.ceil(points.length / 8));
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    labels.forEach((label, index) => {
      if (index % stride !== 0 && index !== labels.length - 1) return;
      ctx.fillText(
        String(label),
        pad.left + index * step + step / 2,
        height - pad.bottom + 8
      );
    });
  }

  window.SSCCharts = { line, bars, empty, formatDate, formatNumber };
})();