"""Flask web dashboard for the Huygens printer CLI."""

import atexit
import os
import shutil
import tempfile
import threading
import time

import av as _av
import requests as _requests
from flask import Flask, Response, jsonify, render_template_string, request, send_from_directory

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
  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
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
    .dot.printing { background: var(--green);  box-shadow: 0 0 7px var(--green); }
    .dot.idle     { background: var(--muted); }
    .dot.offline  { background: var(--orange); }
    .dot.error    { background: var(--red);    box-shadow: 0 0 7px var(--red); }
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
    .video-pane video, .video-pane img {
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      display: block;
    }
    .video-overlay {
      display: flex; flex-direction: column; align-items: center;
      justify-content: center; gap: 16px; color: var(--muted); text-align: center;
    }
    .video-overlay svg { opacity: .3; }
    .video-overlay p { font-size: 13px; }
    .stream-btn {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 10px 22px; border-radius: 8px; border: 1px solid var(--border);
      background: var(--surface); color: var(--text);
      font-size: 13px; font-weight: 500; cursor: pointer;
      transition: background 0.15s, border-color 0.15s;
    }
    .stream-btn:hover  { background: #21262d; border-color: var(--blue); color: var(--blue); }
    .stream-btn:active { background: #161b22; }
    .stream-btn:disabled { opacity: .45; cursor: not-allowed; }
    .stream-btn.active { border-color: var(--red); color: var(--red); }
    .stream-btn.active:hover { background: rgba(248,81,73,.08); }

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
    <video id="webcam" autoplay muted playsinline style="display:none;width:100%;height:100%;object-fit:contain;"></video>
    <div class="video-overlay" id="video-overlay">
      <svg width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.2" viewBox="0 0 24 24">
        <path d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9A2.25 2.25 0 0013.5 5.25h-9A2.25 2.25 0 002.25 9v9A2.25 2.25 0 004.5 18.75z"/>
      </svg>
      <button class="stream-btn" id="stream-btn" onclick="toggleStream()">
        <svg width="14" height="14" fill="currentColor" viewBox="0 0 16 16"><path d="M3 2.5v11l10-5.5L3 2.5z"/></svg>
        Start Stream
      </button>
      <p id="stream-msg" style="font-size:12px;min-height:1em"></p>
    </div>
  </div>

  <div class="status-pane" id="status-pane">
    <div class="card">
      <div class="card-title">Upload</div>
      <div id="upload-idle">
        <input type="file" id="upload-input" accept=".goo,.ctb" style="display:none">
        <button class="stream-btn" style="width:100%;justify-content:center"
                onclick="document.getElementById('upload-input').click()">
          <svg width="14" height="14" fill="currentColor" viewBox="0 0 16 16"><path d="M8 1.5l4 4h-2.5v5h-3v-5H4l4-4zM3 13h10v1.5H3V13z"/></svg>
          Choose file…
        </button>
      </div>
      <div id="upload-active" style="display:none">
        <div class="filename" id="upload-name"></div>
        <div class="progress-bar-bg"><div class="progress-bar-fill" id="upload-bar" style="width:0%"></div></div>
        <div class="progress-labels"><span id="upload-detail"></span><span id="upload-pct">0%</span></div>
      </div>
      <p id="upload-msg" style="font-size:12px;color:var(--muted);margin-top:8px;min-height:1em"></p>
    </div>
    <div id="status-cards">
      <div class="card" style="color:var(--muted);text-align:center;padding:32px">Loading…</div>
    </div>
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
  dot.className = 'dot ' + (d.offline ? 'offline' : d.error_number ? 'error' : d.machine_status === 1 ? 'printing' : 'idle');
  const updated = document.getElementById('hdr-updated');
  updated.textContent = d.offline
    ? 'Offline — last seen ' + new Date().toLocaleTimeString()
    : 'Updated ' + new Date().toLocaleTimeString();
  updated.style.color = d.offline ? 'var(--orange)' : '';
  document.getElementById('ftr-fw').textContent = d.firmware_version ? `Firmware ${d.firmware_version}` : '';

  let html = '';

  // Status card
  html += `<div class="card" ${d.offline ? 'style="opacity:.6"' : ''}>
    <div class="card-title">Status${d.offline ? ' &nbsp;<span style="color:var(--orange);font-weight:400;text-transform:none;letter-spacing:0">· offline</span>' : ''}</div>
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

  document.getElementById('status-cards').innerHTML = html;
}

async function poll() {
  try {
    const resp = await fetch('/api/status');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const d = await resp.json();
    if (d.error && !d.offline) {
      // No cached data yet — still connecting
      document.getElementById('status-cards').innerHTML =
        `<div class="card" style="color:var(--muted);text-align:center;padding:32px">${d.error}</div>`;
    } else {
      render(d);
    }
  } catch (e) {
    // Dashboard server itself unreachable
    document.getElementById('hdr-dot').className = 'dot error';
    document.getElementById('hdr-updated').textContent = 'Dashboard unreachable';
  }
}

// ── Video stream toggle ──
let _hls = null;
let _streaming = false;

function _setStreamUI(active, msg) {
  const btn = document.getElementById('stream-btn');
  const overlay = document.getElementById('video-overlay');
  const video = document.getElementById('webcam');
  const msgEl = document.getElementById('stream-msg');
  if (active) {
    btn.innerHTML = '<svg width="14" height="14" fill="currentColor" viewBox="0 0 16 16"><path d="M5 3.5h2v9H5zm4 0h2v9H9z"/></svg> Stop Stream';
    btn.classList.add('active');
    overlay.style.display = 'none';
    video.style.display = 'block';
  } else {
    btn.innerHTML = '<svg width="14" height="14" fill="currentColor" viewBox="0 0 16 16"><path d="M3 2.5v11l10-5.5L3 2.5z"/></svg> Start Stream';
    btn.classList.remove('active');
    overlay.style.display = 'flex';
    video.style.display = 'none';
  }
  if (msgEl) msgEl.textContent = msg || '';
}

function _startHLS() {
  const video = document.getElementById('webcam');
  const src = '/stream/stream.m3u8';
  if (Hls.isSupported()) {
    _hls = new Hls({ lowLatencyMode: true });
    _hls.loadSource(src);
    _hls.attachMedia(video);
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = src;
  }
}

function _stopHLS() {
  if (_hls) { _hls.destroy(); _hls = null; }
  const video = document.getElementById('webcam');
  video.src = '';
}

async function toggleStream() {
  const btn = document.getElementById('stream-btn');
  btn.disabled = true;

  if (_streaming) {
    _stopHLS();
    _streaming = false;
    _setStreamUI(false, '');
    await fetch('/api/video/stop', { method: 'POST' });
  } else {
    document.getElementById('stream-msg').textContent = 'Starting…';
    const resp = await fetch('/api/video/start', { method: 'POST' });
    const data = await resp.json();
    if (data.error) {
      document.getElementById('stream-msg').textContent = data.error;
    } else {
      _streaming = true;
      _setStreamUI(true);
      _startHLS();
    }
  }

  btn.disabled = false;
}

// ── File upload ──
let _uploadPoll = null;

const uploadInput = document.getElementById('upload-input');
uploadInput.addEventListener('change', () => {
  const f = uploadInput.files[0];
  if (f) startUpload(f);
  uploadInput.value = '';  // allow re-selecting the same file
});

function fmtBytes(b) {
  if (b >= 1048576) return (b / 1048576).toFixed(1) + ' MB';
  if (b >= 1024)    return (b / 1024).toFixed(0) + ' KB';
  return b + ' B';
}

function setUploadUI(active, name) {
  document.getElementById('upload-idle').style.display = active ? 'none' : 'block';
  document.getElementById('upload-active').style.display = active ? 'block' : 'none';
  if (active) {
    document.getElementById('upload-name').textContent = name || '';
    document.getElementById('upload-bar').style.width = '0%';
    document.getElementById('upload-pct').textContent = '0%';
    document.getElementById('upload-detail').textContent = '';
  }
}

function uploadMsg(text, kind) {
  const el = document.getElementById('upload-msg');
  el.textContent = text;
  el.style.color = kind === 'error' ? 'var(--red)' : kind === 'ok' ? 'var(--green)' : 'var(--muted)';
  if (kind) setTimeout(() => {
    if (el.textContent === text) { el.textContent = ''; el.style.color = 'var(--muted)'; }
  }, 6000);
}

async function startUpload(file) {
  setUploadUI(true, file.name);
  uploadMsg('Sending to printer…');
  const fd = new FormData();
  fd.append('file', file);
  let resp;
  try {
    resp = await fetch('/api/upload', { method: 'POST', body: fd });
  } catch (e) {
    return finishUpload('error', 'Upload request failed');
  }
  if (!resp.ok) {
    const d = await resp.json().catch(() => ({}));
    return finishUpload('error', d.error || ('HTTP ' + resp.status));
  }
  pollUpload();
}

function pollUpload() {
  if (_uploadPoll) clearInterval(_uploadPoll);
  _uploadPoll = setInterval(async () => {
    let s;
    try { s = await (await fetch('/api/upload/status')).json(); }
    catch (e) { return; }
    if (s.status === 'uploading') {
      setUploadUI(true, s.filename);
      const pct = s.total ? (s.sent / s.total * 100) : 0;
      document.getElementById('upload-bar').style.width = pct.toFixed(1) + '%';
      document.getElementById('upload-pct').textContent = pct.toFixed(0) + '%';
      document.getElementById('upload-detail').textContent = fmtBytes(s.sent) + ' / ' + fmtBytes(s.total);
    } else if (s.status === 'done') {
      finishUpload('ok', 'Uploaded ' + (s.filename || ''));
    } else if (s.status === 'error') {
      finishUpload('error', s.error || 'Upload failed');
    }
  }, 600);
}

function finishUpload(kind, msg) {
  if (_uploadPoll) { clearInterval(_uploadPoll); _uploadPoll = null; }
  setUploadUI(false);
  uploadMsg(msg, kind);
}

// Resume the progress display if an upload is already running (e.g. after a refresh)
(async () => {
  try {
    const s = await (await fetch('/api/upload/status')).json();
    if (s.status === 'uploading') { setUploadUI(true, s.filename); pollUpload(); }
  } catch (e) {}
})();

poll();
setInterval(poll, POLL_MS);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Video stream control via SDCP CMD 386
# ---------------------------------------------------------------------------

def start_video(ip: str, mainboard_id: str, timeout: float = 10.0) -> str | None:
    """Send Enable=1, return RTSP URL or None on failure."""
    try:
        return _printer.start_video_stream(ip, mainboard_id, timeout)
    except Exception as e:
        return None


def stop_video(ip: str, mainboard_id: str) -> None:
    """Send Enable=0 to release the printer's one connection slot."""
    _printer.stop_video_stream(ip, mainboard_id)


# ---------------------------------------------------------------------------
# RTSP → HLS transcoder (stream-copy, one persistent connection)
# ---------------------------------------------------------------------------

class _HLSTranscoder:
    """Remux RTSP into HLS segments in a temp directory.

    Uses stream-copy (no decode/encode), so CPU overhead is negligible.
    One RTSP session stays open for the lifetime of the server.
    """

    def __init__(self, rtsp_url: str, ip: str, mainboard_id: str):
        self._url = rtsp_url
        self._ip = ip
        self._mid = mainboard_id
        self._dir = tempfile.mkdtemp(prefix="huygens_hls_")
        self._playlist = os.path.join(self._dir, "stream.m3u8")
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        atexit.register(self._cleanup)

    @property
    def directory(self) -> str:
        return self._dir

    @property
    def ready(self) -> bool:
        return os.path.exists(self._playlist)

    def stop(self):
        self._stop.set()

    def _cleanup(self):
        self._stop.set()
        _printer.stop_video_stream(self._ip, self._mid)
        shutil.rmtree(self._dir, ignore_errors=True)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._transcode()
            except Exception:
                if not self._stop.is_set():
                    time.sleep(5)

    def _transcode(self):
        inc = _av.open(self._url, options={"rtsp_transport": "tcp"})
        outc = _av.open(
            self._playlist,
            mode="w",
            format="hls",
            options={
                "hls_time": "2",
                "hls_list_size": "5",
                "hls_flags": "delete_segments+append_list",
                "hls_segment_filename": os.path.join(self._dir, "seg%05d.ts"),
            },
        )
        in_stream = inc.streams.video[0]
        out_stream = outc.add_stream(template=in_stream)
        try:
            for packet in inc.demux(in_stream):
                if self._stop.is_set():
                    break
                if packet.dts is None:
                    continue
                packet.stream = out_stream
                outc.mux(packet)
        finally:
            outc.close()
            inc.close()


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
        self._offline = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            try:
                s = _printer.get_status(self._ip, self._mid)
                with self._lock:
                    self._data = s
                    self._offline = False
            except Exception:
                with self._lock:
                    self._offline = True
            time.sleep(self._interval)

    def get(self):
        with self._lock:
            return self._data, self._offline


# ---------------------------------------------------------------------------
# Background file uploader (one upload at a time)
# ---------------------------------------------------------------------------

class _Uploader:
    """Forward a file to the printer in a background thread, tracking progress.

    The browser POSTs the file to the dashboard, which saves it to a temp file
    and streams it on to the printer via the SDCP HTTP endpoint. Progress here
    reflects the dashboard → printer leg, which is the slow part on a LAN.
    """

    def __init__(self, ip: str, mainboard_id: str):
        self._ip = ip
        self._mid = mainboard_id
        self._lock = threading.Lock()
        self._state = {"status": "idle", "filename": None,
                       "sent": 0, "total": 0, "error": None}
        self._thread = None

    def start(self, local_path: str, filename: str) -> bool:
        """Begin an upload. Returns False if one is already running."""
        with self._lock:
            if self._state["status"] == "uploading":
                return False
            self._state = {"status": "uploading", "filename": filename,
                           "sent": 0, "total": os.path.getsize(local_path), "error": None}
        self._thread = threading.Thread(
            target=self._run, args=(local_path, filename), daemon=True)
        self._thread.start()
        return True

    def _run(self, local_path: str, filename: str):
        def on_progress(sent, total):
            with self._lock:
                self._state["sent"] = sent
                self._state["total"] = total
        try:
            _printer.upload_file(self._ip, self._mid, local_path, on_progress=on_progress)
            with self._lock:
                self._state["status"] = "done"
        except Exception as e:
            with self._lock:
                self._state["status"] = "error"
                self._state["error"] = str(e)
        finally:
            try:
                os.remove(local_path)
            except OSError:
                pass

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------

def create_app(cfg: dict, video_url: str | None = None) -> Flask:
    app = Flask(__name__)
    poller = _StatusPoller(cfg["ip"], cfg["mainboard_id"])
    uploader = _Uploader(cfg["ip"], cfg["mainboard_id"])
    _hls = [None]  # mutable box so inner functions can reassign

    @app.route("/")
    def dashboard():
        return render_template_string(
            _DASHBOARD,
            name=cfg["name"],
            ip=cfg["ip"],
            model=cfg.get("machine_name", ""),
        )

    @app.route("/api/video/start", methods=["POST"])
    def video_start():
        if _hls[0] is not None:
            return jsonify({"ok": True})
        try:
            url = video_url or _printer.start_video_stream(cfg["ip"], cfg["mainboard_id"])
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        _hls[0] = _HLSTranscoder(url, cfg["ip"], cfg["mainboard_id"])
        return jsonify({"ok": True})

    @app.route("/api/video/stop", methods=["POST"])
    def video_stop():
        if _hls[0]:
            _hls[0].stop()
            _hls[0] = None
        _printer.stop_video_stream(cfg["ip"], cfg["mainboard_id"])
        return jsonify({"ok": True})

    @app.route("/stream/<path:filename>")
    def stream_file(filename):
        if not _hls[0]:
            return "Stream not active", 404
        if not _hls[0].ready:
            return "Stream not ready yet", 503
        return send_from_directory(_hls[0].directory, filename)

    @app.route("/api/upload", methods=["POST"])
    def api_upload():
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "No file provided"}), 400
        filename = os.path.basename(f.filename)
        if not filename.lower().endswith(_printer.UPLOAD_EXTENSIONS):
            exts = ", ".join(_printer.UPLOAD_EXTENSIONS)
            return jsonify({"error": f"Only {exts} files can be uploaded"}), 400
        fd, tmp_path = tempfile.mkstemp(prefix="huygens_upload_")
        os.close(fd)
        f.save(tmp_path)
        if not uploader.start(tmp_path, filename):
            os.remove(tmp_path)
            return jsonify({"error": "An upload is already in progress"}), 409
        return jsonify({"ok": True})

    @app.route("/api/upload/status")
    def api_upload_status():
        return jsonify(uploader.status())

    @app.route("/api/status")
    def api_status():
        s, offline = poller.get()
        if s is None:
            return jsonify({"offline": True, "error": "Connecting…"})

        return jsonify({
            "offline":              offline,
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
