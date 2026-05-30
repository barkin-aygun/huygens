"""Flask web dashboard for the Huygens printer CLI."""

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

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
    .dot.printing { background: var(--green);  box-shadow: 0 0 7px var(--green); animation: pulse 1.6s ease-in-out infinite; }
    .dot.online   { background: var(--green);  box-shadow: 0 0 7px var(--green); }
    .dot.idle     { background: var(--muted); }
    .dot.offline  { background: var(--orange); }
    .dot.error    { background: var(--red);    box-shadow: 0 0 7px var(--red); }
    @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .45; } }
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
      position: relative;
    }
    .stream-stop {
      position: absolute; top: 12px; right: 12px; z-index: 2;
      display: none; align-items: center; gap: 6px;
      padding: 7px 14px; border-radius: 8px;
      background: rgba(13,17,23,.7); border: 1px solid var(--border);
      color: var(--text); font-size: 12px; font-weight: 500; cursor: pointer;
      backdrop-filter: blur(4px);
    }
    .stream-stop:hover { border-color: var(--red); color: var(--red); }
    .spinner {
      width: 28px; height: 28px; border-radius: 50%;
      border: 3px solid var(--border); border-top-color: var(--blue);
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
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

    /* ── File browser ── */
    .files-head { display: flex; align-items: center; justify-content: space-between; }
    .files-tools { display: flex; align-items: center; gap: 4px; }
    .seg {
      background: var(--bg); color: var(--muted); border: 1px solid var(--border);
      border-radius: 5px; font-size: 11px; padding: 2px 8px; cursor: pointer;
      font-weight: 600; text-transform: none; letter-spacing: 0;
    }
    .seg:hover { color: var(--text); border-color: var(--blue); }
    .seg.active { background: rgba(88,166,255,.15); color: var(--blue); border-color: var(--blue); }
    .icon-btn {
      background: none; border: none; color: var(--muted); cursor: pointer;
      font-size: 14px; line-height: 1; padding: 2px 4px; border-radius: 4px;
    }
    .icon-btn:hover { color: var(--blue); background: var(--bg); }
    .icon-btn:disabled { opacity: .4; cursor: default; }
    .files-path { font-family: monospace; font-size: 11px; color: var(--muted); margin-bottom: 8px; word-break: break-all; }
    .files-list { max-height: 320px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
    .file-row {
      display: flex; align-items: center; gap: 9px; padding: 7px 8px;
      border-radius: 6px; cursor: default;
    }
    .file-row:hover { background: var(--bg); }
    .file-row .file-ico { flex-shrink: 0; display: flex; }
    .file-row.folder { cursor: pointer; }
    .file-name {
      flex: 1; font-size: 12.5px; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap; font-family: monospace;
    }
    .file-tag {
      font-size: 10px; color: var(--muted); border: 1px solid var(--border);
      border-radius: 10px; padding: 0 7px; flex-shrink: 0;
    }
    .file-del {
      background: none; border: none; color: var(--muted); cursor: pointer;
      padding: 3px; border-radius: 4px; flex-shrink: 0; opacity: 0; display: flex;
      transition: opacity .12s, color .12s, background .12s;
    }
    .file-row:hover .file-del { opacity: 1; }
    .file-del:hover { color: var(--red); background: rgba(248,81,73,.12); }
    .file-del:disabled { opacity: .4 !important; cursor: default; }
    .files-empty { color: var(--muted); font-size: 12px; text-align: center; padding: 18px 0; }
    .file-print {
      background: none; border: none; color: var(--muted); cursor: pointer;
      padding: 3px; border-radius: 4px; flex-shrink: 0; opacity: 0; display: flex;
      transition: opacity .12s, color .12s, background .12s;
    }
    .file-row:hover .file-print { opacity: 1; }
    .file-print:hover { color: var(--green); background: rgba(63,185,80,.12); }

    /* ── Print controls ── */
    .ctrl-row { display: flex; gap: 8px; margin-top: 12px; }
    .ctrl-btn {
      flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
      padding: 8px; border-radius: 6px; border: 1px solid var(--border);
      background: var(--bg); color: var(--text); font-size: 12px; font-weight: 500; cursor: pointer;
    }
    .ctrl-btn:hover { border-color: var(--blue); color: var(--blue); }
    .ctrl-btn.danger:hover { border-color: var(--red); color: var(--red); background: rgba(248,81,73,.08); }
    .ctrl-btn:disabled { opacity: .5; cursor: default; }
    .ico-goo { color: var(--blue); }
    .ico-ctb { color: var(--green); }
    .ico-other { color: var(--muted); }
    .ico-folder { color: var(--orange); }

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
      <div id="video-icon">
        <svg width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.2" viewBox="0 0 24 24">
          <path d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9A2.25 2.25 0 0013.5 5.25h-9A2.25 2.25 0 002.25 9v9A2.25 2.25 0 004.5 18.75z"/>
        </svg>
      </div>
      <div id="video-spinner" class="spinner" style="display:none"></div>
      <button class="stream-btn" id="stream-btn" onclick="startStream()">
        <svg width="14" height="14" fill="currentColor" viewBox="0 0 16 16"><path d="M3 2.5v11l10-5.5L3 2.5z"/></svg>
        Start Stream
      </button>
      <p id="stream-msg" style="font-size:12px;min-height:1em"></p>
    </div>
    <button class="stream-stop" id="stream-stop" onclick="stopStream()">
      <svg width="13" height="13" fill="currentColor" viewBox="0 0 16 16"><path d="M3.5 3.5h9v9h-9z"/></svg>
      Stop
    </button>
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

    <div class="card" id="device-card" style="display:none">
      <div class="card-title">Device</div>
      <div id="device-body"></div>
    </div>

    <div class="card" id="files-card">
      <div class="card-title files-head">
        <span>Files</span>
        <span class="files-tools">
          <button class="seg active" id="seg-local" onclick="setStorage('/local/')">Local</button>
          <button class="seg" id="seg-usb" onclick="setStorage('/usb/')">USB</button>
          <button class="icon-btn" id="files-refresh" title="Refresh" onclick="loadFiles()">&#x21bb;</button>
        </span>
      </div>
      <div class="files-path" id="files-path"></div>
      <div class="files-list" id="files-list"><div class="files-empty">Loading…</div></div>
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
  dot.className = 'dot ' + (d.offline ? 'offline' : d.error_number ? 'error' : d.machine_status === 1 ? 'printing' : 'online');
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
    const isPaused = d.print_status === 6;                       // Paused
    const isActive = d.machine_status === 1 || [1,2,3,4,5].includes(d.print_status) || isPaused;
    const PAUSE = '<svg width="13" height="13" fill="currentColor" viewBox="0 0 16 16"><path d="M5 3.5h2v9H5zm4 0h2v9H9z"/></svg>';
    const PLAY  = '<svg width="13" height="13" fill="currentColor" viewBox="0 0 16 16"><path d="M3 2.5v11l10-5.5z"/></svg>';
    const STOP  = '<svg width="13" height="13" fill="currentColor" viewBox="0 0 16 16"><path d="M3.5 3.5h9v9h-9z"/></svg>';
    let controls = '';
    if (isActive) {
      controls = `<div class="ctrl-row">
        ${isPaused
          ? `<button class="ctrl-btn" onclick="printResume()">${PLAY} Resume</button>`
          : `<button class="ctrl-btn" onclick="printPause()">${PAUSE} Pause</button>`}
        <button class="ctrl-btn danger" onclick="printStop()">${STOP} Stop</button>
      </div>`;
    }
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
      ${controls}
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
  const fepMax = _attrs && _attrs.release_film_max;
  const fep = fepMax
    ? `${d.release_film_count.toLocaleString()} / ${fepMax.toLocaleString()} <span style="color:var(--muted)">(${(d.release_film_count / fepMax * 100).toFixed(0)}%)</span>`
    : d.release_film_count.toLocaleString();
  html += `<div class="card">
    <div class="card-title">Details</div>
    <div class="row">
      <span class="row-label">FEP cycles</span>
      <span class="row-value">${fep}</span>
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

// ── Video stream ──
let _hls = null;
let _streaming = false;

// state: 'idle' | 'buffering' | 'playing'
function _setStreamUI(state, msg) {
  const overlay = document.getElementById('video-overlay');
  const video   = document.getElementById('webcam');
  const stopBtn = document.getElementById('stream-stop');
  const startBtn= document.getElementById('stream-btn');
  const icon    = document.getElementById('video-icon');
  const spinner = document.getElementById('video-spinner');
  const msgEl   = document.getElementById('stream-msg');

  const playing = state === 'playing';
  overlay.style.display = playing ? 'none' : 'flex';
  video.style.display   = playing ? 'block' : 'none';
  stopBtn.style.display = (state === 'idle') ? 'none' : 'inline-flex';

  const buffering = state === 'buffering';
  startBtn.style.display = buffering ? 'none' : 'inline-flex';
  icon.style.display     = buffering ? 'none' : 'block';
  spinner.style.display  = buffering ? 'block' : 'none';

  if (msgEl) msgEl.textContent = msg || '';
}

async function _waitForStream(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!_streaming) return false;            // user pressed Stop while waiting
    try {
      // Poll the readiness flag (always 200) rather than the playlist, which
      // 503s until ready and would spam the console with failed requests.
      const d = await (await fetch('/api/video/ready', { cache: 'no-store' })).json();
      if (d.ready) return true;
    } catch (e) {}
    await new Promise(r => setTimeout(r, 700));
  }
  return false;
}

async function startStream() {
  if (_streaming) return;
  _streaming = true;
  _setStreamUI('buffering', 'Starting camera…');

  let data;
  try {
    data = await (await fetch('/api/video/start', { method: 'POST' })).json();
  } catch (e) { data = { error: 'Could not reach dashboard' }; }
  if (!_streaming) return;                     // stopped during the request
  if (data.error) { _streaming = false; _setStreamUI('idle', data.error); return; }

  _setStreamUI('buffering', 'Buffering…');
  const ready = await _waitForStream(25000);
  if (!_streaming) return;
  if (!ready) { await stopStream(); _setStreamUI('idle', 'Stream did not start'); return; }

  const video = document.getElementById('webcam');
  const src = '/stream/stream.m3u8';
  if (window.Hls && Hls.isSupported()) {
    _hls = new Hls({
      lowLatencyMode: true,
      liveSyncDurationCount: 2,        // sit ~2 segments behind live, not the default 3
      liveMaxLatencyDurationCount: 5,
      maxLiveSyncPlaybackRate: 1.5,    // speed up gently to chase the live edge
      manifestLoadingMaxRetry: 8,
      manifestLoadingRetryDelay: 800,
    });
    _hls.loadSource(src);
    _hls.attachMedia(video);
    _hls.on(Hls.Events.MANIFEST_PARSED, () => {
      _setStreamUI('playing');
      video.play().catch(() => {});
    });
    _hls.on(Hls.Events.ERROR, (evt, d) => {
      if (!d.fatal) return;
      if (d.type === Hls.ErrorTypes.NETWORK_ERROR) _hls.startLoad();
      else if (d.type === Hls.ErrorTypes.MEDIA_ERROR) _hls.recoverMediaError();
    });
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = src;                           // Safari native HLS
    video.addEventListener('loadeddata', () => _setStreamUI('playing'), { once: true });
    video.play().catch(() => {});
  }
}

async function stopStream() {
  _streaming = false;
  if (_hls) { _hls.destroy(); _hls = null; }
  const video = document.getElementById('webcam');
  video.removeAttribute('src');
  video.load();
  _setStreamUI('idle', '');
  try { await fetch('/api/video/stop', { method: 'POST' }); } catch (e) {}
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
      if (typeof loadFiles === 'function') loadFiles();
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

// ── File browser ──
let _storage = '/local/';
let _path = '/local/';

const FILE_ICON = '<svg width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.4" viewBox="0 0 24 24"><path d="M6 2.5h7l5 5v14H6z"/><path d="M13 2.5V8h5"/></svg>';
const FOLDER_ICON = '<svg width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.4" viewBox="0 0 24 24"><path d="M3 6.5h6l2 2.5h10v11H3z"/></svg>';
const UP_ICON = '<svg width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.4" viewBox="0 0 24 24"><path d="M5 12l7-7 7 7M12 5v15"/></svg>';

function extClass(name) {
  const n = name.toLowerCase();
  if (n.endsWith('.goo')) return 'ico-goo';
  if (n.endsWith('.ctb')) return 'ico-ctb';
  return 'ico-other';
}

function setStorage(s) {
  _storage = s;
  _path = s;
  document.getElementById('seg-local').classList.toggle('active', s === '/local/');
  document.getElementById('seg-usb').classList.toggle('active', s === '/usb/');
  loadFiles();
}

function openFolder(path) { _path = path; loadFiles(); }

function esc(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function loadFiles() {
  const list = document.getElementById('files-list');
  document.getElementById('files-path').textContent = _path;
  const btn = document.getElementById('files-refresh');
  btn.disabled = true;
  let data;
  try {
    const resp = await fetch('/api/files?path=' + encodeURIComponent(_path));
    data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || ('HTTP ' + resp.status));
  } catch (e) {
    list.innerHTML = `<div class="files-empty">Couldn't load files — ${esc(String(e.message || e))}</div>`;
    btn.disabled = false;
    return;
  }
  btn.disabled = false;

  let html = '';
  if (_path !== _storage) {
    let trimmed = _path;
    while (trimmed.endsWith('/')) trimmed = trimmed.slice(0, -1);
    const up = trimmed.split('/').slice(0, -1).join('/') || _storage;
    html += `<div class="file-row folder" onclick="openFolder('${esc(up)}')">
      <span class="file-ico ico-folder">${UP_ICON}</span><span class="file-name">..</span></div>`;
  }

  const folders = data.entries.filter(e => e.is_folder);
  const files = data.entries.filter(e => !e.is_folder);

  for (const e of folders) {
    html += `<div class="file-row folder" onclick="openFolder('${esc(e.path)}')">
      <span class="file-ico ico-folder">${FOLDER_ICON}</span>
      <span class="file-name">${esc(e.name)}/</span></div>`;
  }
  for (const e of files) {
    html += `<div class="file-row">
      <span class="file-ico ${extClass(e.name)}">${FILE_ICON}</span>
      <span class="file-name" title="${esc(e.name)}">${esc(e.name)}</span>
      <span class="file-tag">${esc(e.storage)}</span>
      <button class="file-print" title="Print" onclick='startPrint(${JSON.stringify(e.path)}, ${JSON.stringify(e.name)})'>
        <svg width="15" height="15" fill="currentColor" viewBox="0 0 16 16"><path d="M3 2.5v11l10-5.5z"/></svg>
      </button>
      <button class="file-del" title="Delete" onclick='deleteFile(${JSON.stringify(e.path)}, ${JSON.stringify(e.name)})'>
        <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>
      </button></div>`;
  }

  if (!folders.length && !files.length && _path === _storage) {
    html = `<div class="files-empty">No files on ${_storage === '/usb/' ? 'USB' : 'local storage'}</div>`;
  }
  list.innerHTML = html;
}

async function deleteFile(path, name) {
  if (!confirm('Delete "' + name + '" from the printer? This cannot be undone.')) return;
  const list = document.getElementById('files-list');
  list.querySelectorAll('.file-del').forEach(b => b.disabled = true);
  try {
    const resp = await fetch('/api/files/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths: [path] }),
    });
    const d = await resp.json();
    if (!resp.ok || d.error) throw new Error(d.error || ('HTTP ' + resp.status));
    if (d.failed && d.failed.length) throw new Error('Printer could not delete the file');
  } catch (e) {
    alert('Delete failed: ' + (e.message || e));
  }
  loadFiles();
}

// ── Print control ──
async function _printAction(path, label) {
  try {
    const r = await fetch(path, { method: 'POST' });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || ('HTTP ' + r.status));
  } catch (e) { alert(label + ' failed: ' + (e.message || e)); }
  poll();
}
function printPause()  { _printAction('/api/print/pause', 'Pause'); }
function printResume() { _printAction('/api/print/resume', 'Resume'); }
function printStop() {
  if (!confirm('Stop the current print? This cannot be undone.')) return;
  _printAction('/api/print/stop', 'Stop');
}

async function startPrint(path, name) {
  if (!confirm('Start printing "' + name + '" on the printer?')) return;
  try {
    const r = await fetch('/api/print/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: path }),
    });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || ('HTTP ' + r.status));
  } catch (e) { alert('Could not start print: ' + (e.message || e)); return; }
  poll();
}

// ── Device attributes ──
let _attrs = null;

function fmtGB(bytes) {
  if (!bytes) return '—';
  const gb = bytes / 1e9;
  return (gb >= 1 ? gb.toFixed(1) + ' GB' : (bytes/1e6).toFixed(0) + ' MB');
}

function devRow(label, value) {
  return `<div class="row"><span class="row-label">${label}</span><span class="row-value">${value}</span></div>`;
}

function renderDevice() {
  const a = _attrs;
  const card = document.getElementById('device-card');
  if (!a || !a.firmware && !a.resolution) { card.style.display = 'none'; return; }
  card.style.display = 'block';

  const slotsBusy = a.video_streams_used > 0;
  const slots = `<span class="${slotsBusy ? '' : ''}" style="color:${slotsBusy ? 'var(--blue)' : 'var(--text)'}">${a.video_streams_used} / ${a.video_streams_max}</span>`;
  const build = a.xyz_size ? a.xyz_size.replace(/x/g, ' × ') + ' mm' : '—';
  const res = a.resolution ? a.resolution.replace(/x/g, ' × ') : '—';

  // component health
  const ds = a.devices_status || {};
  const vals = Object.values(ds);
  const bad = vals.filter(v => v !== 1).length;
  const health = !vals.length ? '—'
    : bad === 0 ? badge('All OK', 'g')
    : badge(bad + ' fault' + (bad > 1 ? 's' : ''), 'r');

  let html = '';
  html += devRow('Video streams', slots);
  html += devRow('Storage free', fmtGB(a.remaining_memory));
  html += devRow('USB', a.usb_present ? badge('Inserted', 'b') : badge('None', 'm'));
  html += devRow('Build volume', build);
  html += devRow('Resolution', res + ' px');
  html += devRow('Network', a.network ? a.network.toUpperCase() : '—');
  html += devRow('Components', health);
  document.getElementById('device-body').innerHTML = html;

  // Disable the USB tab in the file browser when no stick is present
  const usbSeg = document.getElementById('seg-usb');
  if (usbSeg) {
    usbSeg.disabled = !a.usb_present;
    usbSeg.style.opacity = a.usb_present ? '' : '.4';
    usbSeg.title = a.usb_present ? '' : 'No USB drive inserted';
  }
}

async function pollAttributes() {
  try {
    _attrs = await (await fetch('/api/attributes')).json();
    renderDevice();
  } catch (e) {}
}

loadFiles();
pollAttributes();
setInterval(pollAttributes, 8000);

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
    """Remux the printer's RTSP feed into HLS segments via the ffmpeg CLI.

    We shell out to ffmpeg rather than use PyAV because this printer's stream
    is awkward in two ways that libav's strict muxer can't tolerate:
      * its RTSP server only accepts UDP transport (TCP -> "Nonmatching
        transport in server reply"), and
      * it emits non-monotonic DTS, which libav rejects outright.
    ffmpeg auto-corrects the timestamps, and `-use_wallclock_as_timestamps`
    regenerates clean ~2s segment timing while still stream-copying (no
    re-encode, so CPU stays negligible).
    """

    def __init__(self, rtsp_url: str, ip: str, mainboard_id: str):
        self._url = rtsp_url
        self._ip = ip
        self._mid = mainboard_id
        self._dir = tempfile.mkdtemp(prefix="huygens_hls_")
        self._playlist = os.path.join(self._dir, "stream.m3u8")
        self._stop = threading.Event()
        self._proc = None
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
        self._kill_proc()

    def _kill_proc(self):
        p = self._proc
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()

    def _cleanup(self):
        self._stop.set()
        self._kill_proc()
        _printer.stop_video_stream(self._ip, self._mid)
        shutil.rmtree(self._dir, ignore_errors=True)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._run_ffmpeg()
            except Exception as e:
                if not self._stop.is_set():
                    # Surface the failure instead of looping silently — this is
                    # how a "Start Stream" that shows nothing becomes debuggable.
                    print(f"[huygens] HLS ffmpeg error: {e}", file=sys.stderr)
            if not self._stop.is_set():
                time.sleep(3)

    def _run_ffmpeg(self):
        cmd = [
            "ffmpeg", "-nostdin", "-loglevel", "error",
            "-rtsp_transport", "udp",
            "-use_wallclock_as_timestamps", "1",
            "-i", self._url,
            "-c", "copy",
            "-f", "hls",
            "-hls_time", "2",
            "-hls_list_size", "3",   # smaller live window => less room to lag behind
            "-hls_flags", "delete_segments+append_list+omit_endlist",
            "-hls_segment_filename", os.path.join(self._dir, "seg%05d.ts"),
            self._playlist,
        ]
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if self._stop.is_set():            # stop() raced with startup
            self._kill_proc()
            return
        _, err = self._proc.communicate()  # blocks until ffmpeg exits / is killed
        if not self._stop.is_set() and self._proc.returncode:
            tail = (err.decode(errors="replace").strip().splitlines() or [""])[-1]
            raise RuntimeError(f"ffmpeg exited {self._proc.returncode}: {tail}")


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


class _AttributesPoller:
    """Poll the printer's attributes (Cmd 1) on a slow cadence — they change
    rarely (USB inserted, video slots, free space), so 8s is plenty."""

    def __init__(self, ip: str, mainboard_id: str, interval: float = 8.0):
        self._ip = ip
        self._mid = mainboard_id
        self._interval = interval
        self._lock = threading.Lock()
        self._data = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            try:
                a = _printer.get_attributes(self._ip, self._mid)
                with self._lock:
                    self._data = a
            except Exception:
                pass
            time.sleep(self._interval)

    def get(self):
        with self._lock:
            return self._data


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
            _printer.upload_file(self._ip, self._mid, local_path,
                                 on_progress=on_progress, remote_filename=filename)
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
    attrs_poller = _AttributesPoller(cfg["ip"], cfg["mainboard_id"])
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
        if shutil.which("ffmpeg") is None:
            return jsonify({"error": "ffmpeg not found — install it to view the stream"}), 500
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

    @app.route("/api/video/ready")
    def video_ready():
        # Always 200 so the client can poll during startup without the browser
        # logging a 503 for every probe of the not-yet-ready HLS playlist.
        return jsonify({"ready": bool(_hls[0] and _hls[0].ready)})

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

    @app.route("/api/attributes")
    def api_attributes():
        a = attrs_poller.get()
        if a is None:
            return jsonify({})
        return jsonify({
            "video_streams_used": a.video_streams_used,
            "video_streams_max":  a.video_streams_max,
            "usb_present":        a.usb_present,
            "remaining_memory":   a.remaining_memory,
            "release_film_max":   a.release_film_max,
            "resolution":         a.resolution,
            "xyz_size":           a.xyz_size,
            "supported_file_types": a.supported_file_types,
            "network":            a.network,
            "firmware":           a.firmware,
            "capabilities":       a.capabilities,
            "devices_status":     a.devices_status,
        })

    @app.route("/api/print/start", methods=["POST"])
    def api_print_start():
        body = request.get_json(silent=True) or {}
        filename = (body.get("filename") or "").strip()
        if not filename:
            return jsonify({"error": "No filename provided"}), 400
        try:
            _printer.start_print(cfg["ip"], cfg["mainboard_id"], filename,
                                 int(body.get("start_layer", 0)))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"ok": True})

    def _print_action(fn):
        try:
            fn(cfg["ip"], cfg["mainboard_id"])
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"ok": True})

    @app.route("/api/print/pause", methods=["POST"])
    def api_print_pause():
        return _print_action(_printer.pause_print)

    @app.route("/api/print/resume", methods=["POST"])
    def api_print_resume():
        return _print_action(_printer.resume_print)

    @app.route("/api/print/stop", methods=["POST"])
    def api_print_stop():
        return _print_action(_printer.stop_print)

    @app.route("/api/files")
    def api_files():
        path = request.args.get("path", "/local/")
        try:
            entries = _printer.list_files(cfg["ip"], cfg["mainboard_id"], path)
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({
            "path": path,
            "entries": [{
                "name": e.name.rstrip("/").rsplit("/", 1)[-1] or e.name,
                "path": e.name,
                "is_folder": e.is_folder,
                "storage": e.storage_label,
            } for e in entries],
        })

    @app.route("/api/files/delete", methods=["POST"])
    def api_files_delete():
        body = request.get_json(silent=True) or {}
        files = body.get("paths", [])
        folders = body.get("folders", [])
        if not files and not folders:
            return jsonify({"error": "Nothing to delete"}), 400
        try:
            failed = _printer.delete_files(cfg["ip"], cfg["mainboard_id"], files, folders)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"ok": not failed, "failed": failed})

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
