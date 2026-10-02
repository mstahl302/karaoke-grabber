"""Persisted settings and an append-only log.

Both live under ~/Library/Application Support/Karaoke Grabber/. Every
function is best-effort: a missing or unreadable file falls back to
defaults and never raises.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

APP_DIR = Path.home() / "Library" / "Application Support" / "Karaoke Grabber"
SETTINGS_PATH = APP_DIR / "settings.json"
LOG_PATH = APP_DIR / "karaoke-grabber.log"

DEFAULTS: dict = {
    "last_save_folder": "",
}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        raw = json.loads(SETTINGS_PATH.read_text())
    except (OSError, ValueError):
        return data
    if isinstance(raw, dict):
        for key in DEFAULTS:
            if key in raw and isinstance(raw[key], type(DEFAULTS[key])):
                data[key] = raw[key]
    return data


def save(data: dict) -> None:
    merged = {key: data.get(key, DEFAULTS[key]) for key in DEFAULTS}
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(merged, indent=2))
    except OSError:
        pass


def log(line: str) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as fh:
            fh.write(f"{stamp} {line}\n")
    except OSError:
        pass
