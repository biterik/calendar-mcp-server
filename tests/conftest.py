# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""Test fixtures: a local Radicale CalDAV server, an in-memory keyring, and a
populated calendar + registry. No real credentials, no external network.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any

import caldav
import pytest

from calmcp.registry import Registry, parse_registry

USER = "testuser"
PASSWORD = "testpass"
KEYRING_SERVICE = "calmcp/test"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"Radicale did not start on port {port} within {timeout}s")


@pytest.fixture(scope="session")
def radicale_server(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Start a Radicale server in a subprocess; yield its base URL."""
    base = tmp_path_factory.mktemp("radicale")
    storage = base / "collections"
    storage.mkdir()
    users_file = base / "users"
    users_file.write_text(f"{USER}:{PASSWORD}\n", encoding="utf-8")
    config = base / "config"
    config.write_text(
        textwrap.dedent(
            f"""
            [server]
            hosts = 127.0.0.1:{{port}}

            [auth]
            type = htpasswd
            htpasswd_filename = {users_file}
            htpasswd_encryption = plain

            [storage]
            filesystem_folder = {storage}

            [rights]
            type = owner_only

            [logging]
            level = error
            """
        ),
        encoding="utf-8",
    )

    port = _free_port()
    config.write_text(config.read_text().replace("{port}", str(port)), encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, "-m", "radicale", "--config", str(config)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_port(port)
    except RuntimeError as e:
        proc.terminate()
        err = proc.stderr.read().decode() if proc.stderr else ""
        raise RuntimeError(f"Radicale failed to start:\n{err}") from e

    yield f"http://127.0.0.1:{port}"

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


SINGLE_EVENT = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//calmcp-tests//EN
BEGIN:VEVENT
UID:meeting-1@test
SUMMARY:Project Sync
DTSTART:20260610T090000Z
DTEND:20260610T100000Z
LOCATION:Room A
END:VEVENT
END:VCALENDAR
"""

RECURRING_EVENT = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//calmcp-tests//EN
BEGIN:VEVENT
UID:standup-1@test
SUMMARY:Daily Standup
DTSTART:20260601T080000Z
DTEND:20260601T081500Z
RRULE:FREQ=WEEKLY;COUNT=5
END:VEVENT
END:VCALENDAR
"""


@pytest.fixture(scope="session")
def calendar_url(radicale_server: str) -> str:
    """Create a populated calendar on the server; return its collection URL."""
    client = caldav.DAVClient(
        url=f"{radicale_server}/", username=USER, password=PASSWORD
    )
    principal = client.principal()
    cal = principal.make_calendar(name="Test Calendar", cal_id="testcal")
    cal.save_event(SINGLE_EVENT)
    cal.save_event(RECURRING_EVENT)
    return str(cal.url)


@pytest.fixture
def memory_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap in an in-memory keyring backend holding the test password."""
    import keyring
    from keyring.backend import KeyringBackend

    class MemoryKeyring(KeyringBackend):
        priority = 1  # type: ignore[assignment]

        def __init__(self) -> None:
            super().__init__()
            self._store: dict[tuple[str, str], str] = {}

        def get_password(self, service: str, username: str) -> str | None:
            return self._store.get((service, username))

        def set_password(self, service: str, username: str, password: str) -> None:
            self._store[(service, username)] = password

        def delete_password(self, service: str, username: str) -> None:
            self._store.pop((service, username), None)

    backend = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(keyring, "get_password", backend.get_password)
    monkeypatch.setattr(keyring, "set_password", backend.set_password)
    keyring.set_password(KEYRING_SERVICE, USER, PASSWORD)


def _make_registry(radicale_server: str, cal_url: str, role: str, owner: str | None) -> Registry:
    cal: dict[str, object] = {"id": "work", "account": "testacct", "role": role, "url": cal_url}
    if owner:
        cal["owner"] = owner
    return parse_registry(
        {
            "accounts": {
                "testacct": {
                    "url": f"{radicale_server}/",
                    "username": USER,
                    "keyring_service": KEYRING_SERVICE,
                }
            },
            "calendars": [cal],
            "defaults": {"timezone": "Europe/Berlin"},
        }
    )


@pytest.fixture
def fresh_calendar(radicale_server: str, memory_keyring: None) -> Any:
    """Create a unique, empty calendar on the server and return its caldav object."""
    client = caldav.DAVClient(
        url=f"{radicale_server}/", username=USER, password=PASSWORD
    )
    principal = client.principal()
    cid = "w" + uuid.uuid4().hex[:8]
    return principal.make_calendar(name="Writable", cal_id=cid)


@pytest.fixture
def writable(radicale_server: str, fresh_calendar: Any) -> tuple[Registry, Any]:
    """An owner-role registry + caldav calendar for write tests."""
    reg = _make_registry(radicale_server, str(fresh_calendar.url), "owner", None)
    return reg, fresh_calendar


@pytest.fixture
def foreign(radicale_server: str, fresh_calendar: Any) -> tuple[Registry, Any]:
    """A non-owned (writable-role) registry to exercise the foreign-write gate."""
    reg = _make_registry(radicale_server, str(fresh_calendar.url), "writable", "someone")
    return reg, fresh_calendar


@pytest.fixture
def writable_registry_file(
    tmp_path: Path, radicale_server: str, fresh_calendar: Any
) -> Path:
    """An owner-role calendars.yaml file (for CLI write tests)."""
    p = tmp_path / "calendars.yaml"
    p.write_text(
        textwrap.dedent(
            f"""
            accounts:
              testacct:
                url: {radicale_server}/
                username: {USER}
                keyring_service: {KEYRING_SERVICE}
            calendars:
              - id: work
                account: testacct
                role: owner
                url: {fresh_calendar.url}
            defaults:
              timezone: Europe/Berlin
            """
        ),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def audit_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect the audit log into a temp dir."""
    d = tmp_path / "state"
    monkeypatch.setenv("CALMCP_STATE_DIR", str(d))
    return d / "audit.jsonl"


@pytest.fixture
def registry_file(
    tmp_path: Path, radicale_server: str, calendar_url: str
) -> Path:
    """Write a calendars.yaml pointing at the Radicale fixture."""
    p = tmp_path / "calendars.yaml"
    p.write_text(
        textwrap.dedent(
            f"""
            accounts:
              testacct:
                url: {radicale_server}/
                username: {USER}
                keyring_service: {KEYRING_SERVICE}
                verify_ssl: true
            calendars:
              - id: work
                account: testacct
                role: owner
                url: {calendar_url}
            defaults:
              write_calendar: work
              timezone: Europe/Berlin
            """
        ),
        encoding="utf-8",
    )
    return p
