"""Flask web dashboard for the Huygens printer CLI."""

import threading
import time

import av as _av
import requests as _requests
from flask import Flask, Response, jsonify, render_template_string

from . import printer as _printer

# ---------------------------------------------------------------------------
# HTML dashboard template
# ---------------------------------------------------------------------------

_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ name }} — Huygens</title>
  <style>
    :root {
      --bg:      #0d1117;
      --surface: #161b22;
      --border:  #30363d;
      --text:    #c9d1d9;
      --muted:   #8b949e;
      --blue:    #58a6ff;
      --green:   #3fb950;
      --orange:  #d29922;
      --red:     #f85149;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
      font-size: 14px;
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    /* ── Header ── */
    header {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px 20px;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
      flex-shrink: 0;
    }
    header h1 { font-size: 15px; font-weight: 600; }
    .header-meta { color: var(--muted); font-size: 12px; }
    .dot {
      width: 9px; height: 9px; border-radius: 50%;
      background: var(--muted); flex-shrink: 0;
      transition: background 0.4s, box-shadow 0.4s;
    }
    .dot.printing { background: var(--green); box-shadow: 0 0 7px var(--green); }
    .dot.idle     { background: var(--muted); }
    .dot.error    { background: var(--red);   box-shadow: 0 0 7px var(--red); }
    .header-right { margin-left: auto; color: var(--muted); font-size: 12px; display: flex; align-items: center; gap: 16px; }

    /* ── Main layout ── */
    main {
      display: grid;
      grid-template-columns: 1fr 360px;
      flex: 1;
      overflow: hidden;
    }

    /* ── Video pane ── */
    .video-pane {
      background: #000;
      border-right: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    .video-pane img {
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      display: block;
    }
    .no-video {
      color: var(--muted);
      text-align: center;
    }
    .no-video svg { opacity: .4; margin-bottom: 12px; }
    .no-video p { font-size: 13px; }
    .no-video code { font-size: 12px; background: var(--surface); padding: 2px 6px; border-radius: 4px; }

    /* ── Status pane ── */
    .status-pane {
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding: 16px;
      overflow-y: auto;
    }

    /* ── Cards ── */
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px 16px;
    }
    .card-title {
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .1em;
      color: var(--muted);
      margin-bottom: 12px;
    }
    .row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    .row:last-child { margin-bottom: 0; }
    .row-label { color: var(--muted); font-size: 13px; }
    .row-value { font-weight: 500; font-size: 13px; }

    /* ── Badges ── */
    .badge {
      display: inline-flex; align-items: center; gap: 5px;
      padding: 2px 9px; border-radius: 12px; font-size: 12px; font-weight: 500;
    }
    .badge-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
    .g  { background: rgba(63,185,80,.15);  color: var(--green); }
    .g  .badge-dot { background: var(--green); }
    .b  { background: rgba(88,166,255,.15); color: var(--blue); }
    .b  .badge-dot { background: var(--blue); }
    .m  { background: rgba(139,148,158,.12);color: var(--muted); }
    .m  .badge-dot { background: var(--muted); }
    .or { background: rgba(210,153,34,.15); color: var(--orange); }
    .or .badge-dot { background: var(--orange); }
    .r  { background: rgba(248,81,73,.15);  color: var(--red); }
    .r  .badge-dot { background: var(--red); }

    /* ── Progress ── */
    .progress-bar-bg {
      background: var(--border);
      border-radius: 4px; height: 7px; overflow: hidden; margin: 10px 0 6px;
    }
    .progress-bar-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--blue) 0%, var(--green) 100%);
      border-radius: 4px;
      transition: width 1.2s ease;
    }
    .progress-labels { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); }
    .filename { font-family: monospace; font-size: 12px; word-break: break-all; color: var(--text); line-height: 1.4; }

    /* ── Time grid ── */
    .time-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .time-block { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; }
    .time-value { font-size: 19px; font-weight: 600; font-variant-numeric: tabular-nums; }
    .time-label { font-size: 11px; color: var(--muted); margin-top: 3px; }

    /* ── Temp row ── */
    .temp-row { display: flex; gap: 10px; }
    .temp-block { flex: 1; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; text-align: center; }
    .temp-value { font-size: 22px; font-weight: 600; color: var(--orange); font-variant-numeric: tabular-nums; }
    .temp-label { font-size: 11px; color: var(--muted); margin-top: 3px; }

    /* ── Error banner ── */
    .error-banner {
      background: rgba(248,81,73,.08); border: 1px solid rgba(248,81,73,.25);
      color: var(--red); border-radius: 6px; padding: 10px 14px; font-size: 13px;
    }

    /* ── Footer ── */
    footer {
      padding: 8px 20px; border-top: 1px solid var(--border);
      color: var(--muted); font-size: 11px;
      display: flex; justify-content: space-between; align-items: center;
      flex-shrink: 0;
    }

    @media (max-width: 680px) {
      body { overflow: auto; }
      main { grid-template-columns: 1fr; }
      .video-pane { min-height: 240px; }
    }
  </style>
</head>
<body>

<header>
  <div class="dot" id="hdr-dot"></div>
  <div>
    <h1>{{ name }}</h1>
    <div class="header-meta">{{ ip }}&ensp;·&ensp;{{ model }}</div>
  </div>
  <div class="header-right">
    <span id="hdr-updated"></span>
  </div>
</header>

<main>
  <div class="video-pane">
    {% if has_video %}
    <img id="webcam" alt="Webcam">
    {% else %}
    <div class="no-video">
      <svg width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.2" viewBox="0 0 24 24">
        <path d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9A2.25 2.25 0 0013.5 5.25h-9A2.25 2.25 0 002.25 9v9A2.25 2.25 0 004.5 18.75z"/>
      </svg>
      <p>No video feed</p>
      <p style="margin-top:6px;"><code>--video-url URL</code> to enable</p>
    </div>
    {% endif %}
  </div>

  <div class="status-pane" id="status-pane">
    <div class="card" style="color:var(--muted);text-align:center;padding:32px">Loading…</div>
  </div>
</main>

<footer>
  <span>huygens</span>
  <span id="ftr-fw"></span>
</footer>

<script>
const POLL_MS = 2500;

const MACHINE_CLS = { 0:'m', 1:'g', 2:'b', 3:'or', 4:'or' };
const PRINT_CLS   = { 0:'m', 1:'or', 2:'b', 3:'g', 4:'b', 5:'or', 6:'or', 7:'r', 8:'r', 9:'g', 10:'b' };

function badge(label, cls) {
  return `<span class="badge ${cls}"><span class="badge-dot"></span>${label}</span>`;
}

function fmtMs(ms) {
  if (!ms) return '—';
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sc = s % 60;
  if (h) return `${h}h ${String(m).padStart(2,'0')}m`;
  return `${m}m ${String(sc).padStart(2,'0')}s`;
}

function render(d) {
  // Header dot
  const dot = document.getElementById('hdr-dot');
  dot.className = 'dot ' + (d.error_number ? 'error' : d.machine_status === 1 ? 'printing' : 'idle');
  document.getElementById('hdr-updated').textContent = new Date().toLocaleTimeString();
  document.getElementById('ftr-fw').textContent = d.firmware_version ? `Firmware ${d.firmware_version}` : '';

  let html = '';

  // Status card
  html += `<div class="card">
    <div class="card-title">Status</div>
    <div class="row">
      <span class="row-label">Machine</span>
      <span class="row-value">${badge(d.machine_status_label, MACHINE_CLS[d.machine_status] || 'm')}</span>
    </div>
    <div class="row">
      <span class="row-label">Print</span>
      <span class="row-value">${badge(d.print_status_label, PRINT_CLS[d.print_status] || 'm')}</span>
    </div>
    ${d.error_number ? `<div class="error-banner" style="margin-top:10px">&#9888; ${d.error_label}</div>` : ''}
  </div>`;

  // Job card
  if (d.filename) {
    const pct = d.progress_pct !== null ? d.progress_pct.toFixed(1) : null;
    html += `<div class="card">
      <div class="card-title">Print Job</div>
      <div class="filename">${d.filename}</div>
      ${pct !== null ? `
      <div class="progress-bar-bg">
        <div class="progress-bar-fill" style="width:${pct}%"></div>
      </div>
      <div class="progress-labels">
        <span>Layer ${d.current_layer.toLocaleString()} / ${d.total_layers.toLocaleString()}</span>
        <span>${pct}%</span>
      </div>` : ''}
    </div>`;
  }

  // Time card
  if (d.elapsed_ms || d.total_ms) {
    html += `<div class="card">
      <div class="card-title">Time</div>
      <div class="time-grid">
        <div class="time-block">
          <div class="time-value">${fmtMs(d.elapsed_ms)}</div>
          <div class="time-label">Elapsed</div>
        </div>
        <div class="time-block">
          <div class="time-value">${fmtMs(d.remaining_ms)}</div>
          <div class="time-label">Remaining</div>
        </div>
      </div>
    </div>`;
  }

  // Temperature card
  if (d.uv_led_temp !== null || d.box_temp !== null) {
    html += `<div class="card">
      <div class="card-title">Temperature</div>
      <div class="temp-row">`;
    if (d.uv_led_temp !== null)
      html += `<div class="temp-block"><div class="temp-value">${d.uv_led_temp.toFixed(1)}°</div><div class="temp-label">UV LED</div></div>`;
    if (d.box_temp !== null)
      html += `<div class="temp-block"><div class="temp-value">${d.box_temp.toFixed(1)}°</div><div class="temp-label">Box</div></div>`;
    html += `</div></div>`;
  }

  // Details card
  html += `<div class="card">
    <div class="card-title">Details</div>
    <div class="row">
      <span class="row-label">FEP cycles</span>
      <span class="row-value">${d.release_film_count.toLocaleString()}</span>
    </div>
    <div class="row">
      <span class="row-label">Timelapse</span>
      <span class="row-value">${d.timelapse_label}</span>
    </div>
    ${d.task_id ? `<div class="row">
      <span class="row-label">Task ID</span>
      <span class="row-value" style="font-family:monospace;font-size:11px;color:var(--muted)">${d.task_id}</span>
    </div>` : ''}
  </div>`;

  document.getElementById('status-pane').innerHTML = html;
}

async function poll() {
  try {
    const resp = await fetch('/api/status');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const d = await resp.json();
    if (d.error) {
      document.getElementById('status-pane').innerHTML =
        `<div class="card error-banner">&#9888; ${d.error}</div>`;
    } else {
      render(d);
    }
  } catch (e) {
    document.getElementById('status-pane').innerHTML =
      `<div class="card error-banner">Connection lost: ${e.message}</div>`;
  }
}

// 1fps snapshot refresh — new URL each tick so browser doesn't cache
const webcam = document.getElementById('webcam');
function refreshWebcam() {
  if (webcam) webcam.src = '/snapshot?' + Date.now();
}
if (webcam) {
  refreshWebcam();
  setInterval(refreshWebcam, 1000);
}

poll();
setInterval(poll, POLL_MS);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Video URL discovery via SDCP CMD 386
# ---------------------------------------------------------------------------

def fetch_video_url(ip: str, mainboard_id: str, timeout: float = 10.0) -> str | None:
    """Ask the printer for its RTSP stream URL via CMD 386."""
    try:
        return _printer.get_video_url(ip, mainboard_id, timeout)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# RTSP → JPEG snapshot (one frame, connection closed immediately)
# ---------------------------------------------------------------------------

def _grab_jpeg(rtsp_url: str) -> bytes:
    """Open the RTSP stream, decode one frame, return it as JPEG bytes."""
    container = _av.open(rtsp_url, options={"rtsp_transport": "tcp"})
    try:
        in_stream = container.streams.video[0]
        frame = next(container.decode(in_stream))
        encoder = _av.CodecContext.create("mjpeg", "w")
        encoder.width = in_stream.width
        encoder.height = in_stream.height
        encoder.pix_fmt = "yuvj420p"
        packets = list(encoder.encode(frame.reformat(format="yuvj420p")))
        return bytes(packets[0])
    finally:
        container.close()


# ---------------------------------------------------------------------------
# Background status poller
# ---------------------------------------------------------------------------

class _StatusPoller:
    def __init__(self, ip: str, mainboard_id: str, interval: float = 2.5):
        self._ip = ip
        self._mid = mainboard_id
        self._interval = interval
        self._lock = threading.Lock()
        self._data = None
        self._error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            try:
                s = _printer.get_status(self._ip, self._mid)
                with self._lock:
                    self._data = s
                    self._error = None
            except Exception as e:
                with self._lock:
                    self._error = str(e)
            time.sleep(self._interval)

    def get(self):
        with self._lock:
            return self._data, self._error


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------

def create_app(cfg: dict, video_url: str | None) -> Flask:
    app = Flask(__name__)
    poller = _StatusPoller(cfg["ip"], cfg["mainboard_id"])

    @app.route("/")
    def dashboard():
        return render_template_string(
            _DASHBOARD,
            name=cfg["name"],
            ip=cfg["ip"],
            model=cfg.get("machine_name", ""),
            has_video=video_url is not None,
        )

    @app.route("/snapshot")
    def snapshot():
        if not video_url:
            return "No video URL configured", 404
        try:
            jpeg = _grab_jpeg(video_url)
            return Response(jpeg, mimetype="image/jpeg")
        except Exception as e:
            return str(e), 502

    @app.route("/api/status")
    def api_status():
        s, err = poller.get()
        if err:
            return jsonify({"error": err})
        if s is None:
            return jsonify({"error": "Waiting for first response…"})
        return jsonify({
            "machine_status":       s.machine_status,
            "machine_status_label": s.machine_status_label,
            "print_status":         s.print_status,
            "print_status_label":   s.print_status_label,
            "filename":             s.filename,
            "current_layer":        s.current_layer,
            "total_layers":         s.total_layers,
            "progress_pct":         s.progress_pct,
            "elapsed_ms":           s.elapsed_ms,
            "remaining_ms":         s.remaining_ms,
            "total_ms":             s.total_ms,
            "uv_led_temp":          s.uv_led_temp,
            "box_temp":             s.box_temp,
            "release_film_count":   s.release_film_count,
            "timelapse_label":      s.timelapse_label,
            "error_number":         s.error_number,
            "error_label":          s.error_label,
            "task_id":              s.task_id,
            "firmware_version":     cfg.get("firmware_version", ""),
        })

    return app
