# Huygens

A command-line tool and web dashboard for the **Elegoo Saturn 4 Ultra 12K**
resin printer, speaking the SDCP (Smart Device Control Protocol) over your local
network. Discover the printer, check status, browse and upload sliced files,
start/pause/stop prints, and watch the built-in camera — all without the vendor
app.

## Requirements

- Python 3.10+
- The printer and your computer on the **same LAN** (discovery uses a UDP
  broadcast)
- [`ffmpeg`](https://ffmpeg.org/) on your `PATH` — only needed for the live
  video stream in the dashboard (the printer's RTSP feed has quirks that require
  remuxing to HLS)

## Install

```bash
pip install -e .
```

This installs the `huygens` command.

## Usage

Discover the printer on your network and save it as the default:

```bash
huygens discover
```

Once a printer is saved, the other commands use it automatically:

```bash
huygens status              # show the saved printer's identity
huygens print-status        # current job: layers, time, temps, progress bar
huygens files               # list printable files on the printer
huygens files -p /usb/      # list files on a USB stick instead
huygens upload model.ctb    # send a sliced .goo/.ctb to internal storage
huygens print-start /local/model.ctb
huygens print-pause
huygens print-resume
huygens print-stop          # asks for confirmation
huygens delete model.ctb    # remove a file from the printer
```

If no printer is saved, the upload/serve commands auto-scan the network and
prompt you to pick one.

### Web dashboard

```bash
huygens serve               # opens http://127.0.0.1:8888 in your browser
huygens serve --host 0.0.0.0 --port 9000   # expose on the LAN
```

The dashboard shows live status, temperatures, device health, a collapsible
file browser (upload, print, delete), print controls, and the camera stream.

## Protocol

Huygens implements the open SDCP specification published by Chitubox/CBD:

- **SDCP (Smart Device Control Protocol) V3.0.0** —
  https://github.com/cbd-tech/SDCP-Smart-Device-Control-Protocol-V3.0.0/blob/main/SDCP(Smart%20Device%20Control%20Protocol)_V3.0.0_EN.md

## Project layout

```
huygens/
  cli.py         # Click CLI entry point
  printer.py     # public API: dataclasses + high-level commands
  _transport.py  # low-level UDP discovery, WebSocket, and HTTP upload
  server.py      # Flask web dashboard
  config.py      # saved-printer config (~/.config/huygens/printer.json)
```
