# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""Append-only audit log for real writes (JSONL).

Every committed write records a timestamped line so changes can be reviewed and
manually undone. Location follows XDG on Linux/macOS
(``~/.local/state/calmcp/audit.jsonl``) and ``%LOCALAPPDATA%`` on Windows; set
``CALMCP_STATE_DIR`` to override (used by tests).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any


def state_dir() -> Path:
    override = os.environ.get("CALMCP_STATE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "calmcp"
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "calmcp"
    return Path.home() / ".local" / "state" / "calmcp"


def audit_path() -> Path:
    return state_dir() / "audit.jsonl"


def append(entry: dict[str, Any]) -> Path:
    """Append one audit entry (with a UTC timestamp) and return the log path."""
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": dt.datetime.now(dt.UTC).isoformat(), **entry}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return path
