import os

import click

from . import config, printer


def _fmt_ms(ms: int) -> str:
    s = ms // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h {m:02d}m {sec:02d}s" if h else f"{m}m {sec:02d}s"


def _resolve_printer(timeout: float = 5.0) -> dict:
    """Return saved config, or auto-discover if none is saved."""
    cfg = config.load()
    if cfg is not None:
        return cfg

    click.echo("No saved printer — scanning network…")
    try:
        printers = printer.discover(timeout=timeout)
    except OSError as e:
        raise SystemExit(str(e))

    if not printers:
        raise SystemExit("No printers found. Run `huygens discover` to save one.")
    if len(printers) == 1:
        p = printers[0]
        click.echo(f"Found: {p.name} ({p.ip})")
        return p.to_dict()

    for i, p in enumerate(printers):
        click.echo(f"  [{i + 1}] {p.name} ({p.ip})")
    idx = click.prompt(
        "Multiple printers found — which one?",
        type=click.IntRange(1, len(printers)),
        default=1,
    )
    return printers[idx - 1].to_dict()


@click.group()
def cli():
    """Huygens — CLI for Elegoo Saturn 4 Ultra (SDCP protocol)."""


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--timeout", "-t", default=5.0, show_default=True,
              help="Seconds to wait for printer responses.")
@click.option("--save/--no-save", default=True, show_default=True,
              help="Save the discovered printer to config.")
def discover(timeout, save):
    """Discover SDCP printers on the local network and save the result."""
    click.echo(f"Broadcasting discovery on UDP port 3000 ({timeout}s)…")
    try:
        printers = printer.discover(timeout=timeout)
    except OSError as e:
        raise SystemExit(str(e))

    if not printers:
        click.echo("No printers found.")
        return

    for i, p in enumerate(printers):
        click.echo(f"\nPrinter {i + 1}:")
        click.echo(f"  Name:         {p.name}")
        click.echo(f"  Model:        {p.machine_name}")
        click.echo(f"  Brand:        {p.brand}")
        click.echo(f"  IP:           {p.ip}")
        click.echo(f"  Mainboard ID: {p.mainboard_id}")
        click.echo(f"  Protocol:     {p.protocol_version}")
        click.echo(f"  Firmware:     {p.firmware_version}")

    if not save:
        return

    chosen = printers[0]
    if len(printers) > 1:
        click.echo()
        for i, p in enumerate(printers):
            click.echo(f"  [{i + 1}] {p.name} ({p.ip})")
        idx = click.prompt(
            "Multiple printers found — which one to save?",
            type=click.IntRange(1, len(printers)),
            default=1,
        )
        chosen = printers[idx - 1]

    config.save(chosen.to_dict())
    click.echo(f"\nSaved {chosen.name} ({chosen.ip}) to {config.CONFIG_FILE}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@cli.command()
def status():
    """Show the currently configured printer."""
    cfg = config.require()
    click.echo(f"Name:         {cfg['name']}")
    click.echo(f"Model:        {cfg['machine_name']}")
    click.echo(f"IP:           {cfg['ip']}")
    click.echo(f"Mainboard ID: {cfg['mainboard_id']}")
    click.echo(f"Protocol:     {cfg['protocol_version']}")
    click.echo(f"Firmware:     {cfg['firmware_version']}")


# ---------------------------------------------------------------------------
# print-status
# ---------------------------------------------------------------------------

@cli.command("print-status")
@click.option("--timeout", "-t", default=10.0, show_default=True,
              help="Seconds to wait for the printer response.")
def print_status(timeout):
    """Show the current print job status."""
    cfg = config.require()
    try:
        s = printer.get_status(cfg["ip"], cfg["mainboard_id"], timeout=timeout)
    except TimeoutError:
        raise SystemExit("Timed out waiting for printer response.")
    except OSError as e:
        raise SystemExit(f"Connection failed: {e}")

    click.echo(f"Machine status:  {s.machine_status_label}")
    click.echo(f"Print status:    {s.print_status_label}")

    if s.filename:
        click.echo(f"File:            {s.filename}")
    if s.task_id:
        click.echo(f"Task ID:         {s.task_id}")
    if s.total_layers:
        bar_width = 30
        filled = int(bar_width * s.current_layer / s.total_layers)
        bar = "#" * filled + "-" * (bar_width - filled)
        click.echo(f"Progress:        [{bar}] {s.progress_pct:.1f}%  (layer {s.current_layer} / {s.total_layers})")
    if s.elapsed_ms or s.total_ms:
        click.echo(f"Elapsed:         {_fmt_ms(s.elapsed_ms)}")
        if s.total_ms:
            click.echo(f"Remaining:       {_fmt_ms(s.remaining_ms)}  (total {_fmt_ms(s.total_ms)})")
    if s.uv_led_temp is not None:
        click.echo(f"UV LED temp:     {s.uv_led_temp:.1f}°C")
    if s.box_temp is not None:
        click.echo(f"Box temp:        {s.box_temp:.1f}°C")
    if s.release_film_count:
        click.echo(f"FEP cycles:      {s.release_film_count:,}")
    click.echo(f"Timelapse:       {s.timelapse_label}")
    if s.error_number:
        click.echo(f"Error:           {s.error_label}")


# ---------------------------------------------------------------------------
# print-start
# ---------------------------------------------------------------------------

@cli.command("print-start")
@click.argument("filename")
@click.option("--start-layer", default=0, show_default=True,
              help="Layer number to start from (0 = beginning).")
@click.option("--timeout", "-t", default=10.0, show_default=True,
              help="Seconds to wait for the printer response.")
def print_start(filename, start_layer, timeout):
    """Start printing FILENAME (a .ctb file on the printer's storage).

    Use /local/file.ctb for onboard storage or /usb/file.ctb for USB.
    If no path prefix is given the printer defaults to /local/.
    """
    cfg = config.require()
    try:
        printer.start_print(
            cfg["ip"], cfg["mainboard_id"], filename, start_layer, timeout
        )
    except TimeoutError:
        raise SystemExit("Timed out waiting for printer response.")
    except OSError as e:
        raise SystemExit(f"Connection failed: {e}")
    except ValueError as e:
        raise SystemExit(f"Printer rejected the request: {e}")

    click.echo(f"Print started: {filename}")


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--path", "-p", default="/local/", show_default=True,
              help="Storage path to list (/local/ or /usb/).")
@click.option("--timeout", "-t", default=10.0, show_default=True,
              help="Seconds to wait for the printer response.")
def files(path, timeout):
    """List printable files on the printer's storage."""
    cfg = config.require()
    try:
        entries = printer.list_files(cfg["ip"], cfg["mainboard_id"], path, timeout)
    except TimeoutError:
        raise SystemExit("Timed out waiting for printer response.")
    except OSError as e:
        raise SystemExit(f"Connection failed: {e}")

    if not entries:
        click.echo(f"No files found at {path}")
        return

    folders = [e for e in entries if e.is_folder]
    file_list = [e for e in entries if not e.is_folder]

    if folders:
        click.echo("Folders:")
        for e in folders:
            click.echo(f"  {e.name}/")

    if file_list:
        click.echo("Files:")
        for e in file_list:
            size_mb = e.used_size / (1024 * 1024) if e.used_size else 0
            click.echo(f"  {e.name}  ({size_mb:.1f} MB)  [{e.storage_label}]")


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("file", type=click.Path(exists=True, readable=True, dir_okay=False))
@click.option("--dest", "-d", default="/local/", show_default=True,
              help="Destination directory on the printer.")
@click.option("--timeout", "-t", default=120.0, show_default=True,
              help="Seconds to wait for the upload to complete.")
def upload(file, dest, timeout):
    """Upload FILE (.ctb) to the printer's storage."""
    cfg = _resolve_printer()
    filename = os.path.basename(file)
    file_size = os.path.getsize(file)
    size_mb = file_size / (1024 * 1024)

    click.echo(f"Uploading {filename} ({size_mb:.1f} MB) to {cfg['name']} ({cfg['ip']})…")

    with click.progressbar(length=file_size, label="  Progress", width=40) as bar:
        last = [0]

        def on_progress(sent, total):
            bar.update(sent - last[0])
            last[0] = sent

        try:
            printer.upload_file(cfg["ip"], file, dest, timeout, on_progress)
        except TimeoutError:
            raise SystemExit("Upload timed out.")
        except OSError as e:
            raise SystemExit(f"Connection failed: {e}")
        except RuntimeError as e:
            raise SystemExit(str(e))

    click.echo(f"Done: {filename}")
