import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "huygens"
CONFIG_FILE = CONFIG_DIR / "printer.json"


def load() -> dict | None:
    if not CONFIG_FILE.exists():
        return None
    with CONFIG_FILE.open() as f:
        return json.load(f)


def save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w") as f:
        json.dump(data, f, indent=2)


def require() -> dict:
    cfg = load()
    if cfg is None:
        raise SystemExit(
            "No printer configured. Run `huygens discover` first."
        )
    return cfg
