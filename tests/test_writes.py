# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""Write operations (create/update/move/delete) against the Radicale fixture."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from calmcp import cli, service
from calmcp.registry import Registry

JUNE = (dt.date(2026, 6, 1), dt.date(2026, 6, 30))

RECURRING = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//calmcp-tests//EN
BEGIN:VEVENT
UID:series-1@test
SUMMARY:Weekly Sync
DTSTART:20260601T080000Z
DTEND:20260601T083000Z
RRULE:FREQ=WEEKLY;COUNT=5
END:VEVENT
END:VCALENDAR
"""


def _summaries(reg: Registry, *, expand: bool = True) -> list[str]:
    result = service.query_events(reg, *JUNE, expand=expand)
    return [e["summary"] for e in result["events"]]


def _occurrences(reg: Registry) -> list[dict[str, Any]]:
    return service.query_events(reg, *JUNE, expand=True)["events"]


# --------------------------------------------------------------------------- create


def test_create_dry_run_writes_nothing(writable: tuple[Registry, Any]) -> None:
    reg, _cal = writable
    result = service.create_event(
        reg, "work", "Dentist", "2026-06-10 09:00", "2026-06-10 09:30"
    )
    assert result["dryRun"] is True
    assert result["action"] == "create"
    assert _summaries(reg) == []


def test_create_confirm_writes_and_audits(
    writable: tuple[Registry, Any], audit_dir: Path
) -> None:
    reg, _cal = writable
    result = service.create_event(
        reg, "work", "Dentist", "2026-06-10 09:00", "2026-06-10 09:30", confirm=True
    )
    assert result["dryRun"] is False
    assert _summaries(reg) == ["Dentist"]

    lines = audit_dir.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["action"] == "create"
    assert entry["calendar"] == "work"
    assert "ts" in entry


def test_create_is_idempotent_upsert(writable: tuple[Registry, Any]) -> None:
    reg, _cal = writable
    for summary in ("First", "Second"):
        service.create_event(
            reg,
            "work",
            summary,
            "2026-06-10 09:00",
            "2026-06-10 09:30",
            uid="fixed@test",
            confirm=True,
        )
    # Same UID -> updated in place, not duplicated.
    assert _summaries(reg) == ["Second"]


def test_create_all_day(writable: tuple[Registry, Any]) -> None:
    reg, _cal = writable
    service.create_event(
        reg, "work", "Holiday", "2026-06-12", "2026-06-12", all_day=True, confirm=True
    )
    events = _occurrences(reg)
    assert len(events) == 1
    assert events[0]["all_day"] is True
    assert events[0]["start"] == "2026-06-12"


# --------------------------------------------------------------------------- update


def test_update_scope_all(writable: tuple[Registry, Any]) -> None:
    reg, _cal = writable
    service.create_event(
        reg, "work", "Old", "2026-06-10 09:00", "2026-06-10 09:30",
        uid="u1@test", confirm=True,
    )
    result = service.update_event(
        reg, "work", "u1@test", {"summary": "New", "location": "Room 9"}, confirm=True
    )
    assert result["before"]["summary"] == "Old"
    assert result["after"]["summary"] == "New"
    events = _occurrences(reg)
    assert events[0]["summary"] == "New"
    assert events[0]["location"] == "Room 9"


def test_update_scope_this_overrides_one_occurrence(
    writable: tuple[Registry, Any],
) -> None:
    reg, cal = writable
    cal.save_event(RECURRING)
    result = service.update_event(
        reg,
        "work",
        "series-1@test",
        {"summary": "Sync (moved room)"},
        recurrence_id="2026-06-08T08:00:00+00:00",
        scope="this",
        confirm=True,
    )
    assert result["scope"] == "this"
    by_date = {e["start"][:10]: e["summary"] for e in _occurrences(reg)}
    assert by_date["2026-06-08"] == "Sync (moved room)"
    # Other occurrences untouched.
    assert by_date["2026-06-01"] == "Weekly Sync"
    assert by_date["2026-06-15"] == "Weekly Sync"


def test_update_unknown_uid_raises(writable: tuple[Registry, Any]) -> None:
    reg, _cal = writable
    try:
        service.update_event(reg, "work", "nope@test", {"summary": "x"}, confirm=True)
    except ValueError as e:
        assert "No event" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


# --------------------------------------------------------------------------- move


def test_move_changes_time(writable: tuple[Registry, Any]) -> None:
    reg, _cal = writable
    service.create_event(
        reg, "work", "Call", "2026-06-10 09:00", "2026-06-10 09:30",
        uid="m1@test", confirm=True,
    )
    service.move_event(
        reg, "work", "m1@test", start="2026-06-10 14:00", end="2026-06-10 14:45",
        confirm=True,
    )
    ev = _occurrences(reg)[0]
    assert ev["start"].startswith("2026-06-10T14:00:00")
    assert ev["end"].startswith("2026-06-10T14:45:00")


# --------------------------------------------------------------------------- delete


def test_delete_all_removes_event(writable: tuple[Registry, Any]) -> None:
    reg, _cal = writable
    service.create_event(
        reg, "work", "Temp", "2026-06-10 09:00", "2026-06-10 09:30",
        uid="d1@test", confirm=True,
    )
    assert _summaries(reg) == ["Temp"]
    result = service.delete_event(reg, "work", "d1@test", confirm=True)
    assert result["after"] is None
    assert _summaries(reg) == []


def test_delete_this_cancels_one_occurrence(writable: tuple[Registry, Any]) -> None:
    reg, cal = writable
    cal.save_event(RECURRING)
    assert len(_occurrences(reg)) == 5
    service.delete_event(
        reg,
        "work",
        "series-1@test",
        recurrence_id="2026-06-08T08:00:00+00:00",
        scope="this",
        confirm=True,
    )
    dates = {e["start"][:10] for e in _occurrences(reg)}
    assert "2026-06-08" not in dates
    assert len(dates) == 4


# --------------------------------------------------------------- thisAndFuture (Phase 4)


def test_this_and_future_delete_bounds_series(writable: tuple[Registry, Any]) -> None:
    reg, cal = writable
    cal.save_event(RECURRING)
    service.delete_event(
        reg,
        "work",
        "series-1@test",
        recurrence_id="2026-06-15T08:00:00+00:00",
        scope="thisAndFuture",
        confirm=True,
    )
    dates = sorted(e["start"][:10] for e in _occurrences(reg))
    assert dates == ["2026-06-01", "2026-06-08"]


def test_this_and_future_update_splits_series(writable: tuple[Registry, Any]) -> None:
    reg, cal = writable
    cal.save_event(RECURRING)
    result = service.update_event(
        reg,
        "work",
        "series-1@test",
        {"summary": "Renamed Sync"},
        recurrence_id="2026-06-15T08:00:00+00:00",
        scope="thisAndFuture",
        confirm=True,
    )
    assert "new_uid" in result
    by_date = {e["start"][:10]: e["summary"] for e in _occurrences(reg)}
    # Before the split: original title; at/after: new title.
    assert by_date["2026-06-01"] == "Weekly Sync"
    assert by_date["2026-06-08"] == "Weekly Sync"
    assert by_date["2026-06-15"] == "Renamed Sync"
    assert by_date["2026-06-22"] == "Renamed Sync"


# --------------------------------------------------------------------------- role gate


def test_foreign_write_refused_without_confirm_foreign(
    foreign: tuple[Registry, Any],
) -> None:
    reg, _cal = foreign
    result = service.create_event(
        reg, "work", "X", "2026-06-10 09:00", "2026-06-10 09:30", confirm=True
    )
    assert result["dryRun"] is True  # refused
    assert any("not owner" in w for w in result["warnings"])
    assert any("confirm_foreign" in w for w in result["warnings"])
    assert _summaries(reg) == []


def test_foreign_write_allowed_with_confirm_foreign(
    foreign: tuple[Registry, Any],
) -> None:
    reg, _cal = foreign
    result = service.create_event(
        reg, "work", "X", "2026-06-10 09:00", "2026-06-10 09:30",
        confirm=True, confirm_foreign=True,
    )
    assert result["dryRun"] is False
    assert any("not owner" in w for w in result["warnings"])
    assert _summaries(reg) == ["X"]


# --------------------------------------------------------------------------- CLI plumbing


def test_cli_create_dry_run_then_confirm(
    capsys: pytest.CaptureFixture[str],
    writable_registry_file: Path,
    audit_dir: Path,
) -> None:
    base = ["--registry", str(writable_registry_file), "create_event",
            "--calendar", "work", "--summary", "CLI Event",
            "--start", "2026-06-10 09:00", "--end", "2026-06-10 09:30"]

    rc = cli.main(base)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert not audit_dir.exists()

    rc = cli.main([*base, "--confirm", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["dryRun"] is False
    assert audit_dir.exists()


def test_cli_foreign_refused_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    radicale_server: str,
    fresh_calendar: Any,
) -> None:
    import textwrap

    from tests.conftest import KEYRING_SERVICE, USER

    reg_file = tmp_path / "cal.yaml"
    reg_file.write_text(
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
                role: writable
                owner: someone
                url: {fresh_calendar.url}
            """
        ),
        encoding="utf-8",
    )
    rc = cli.main(
        ["--registry", str(reg_file), "create_event", "--calendar", "work",
         "--summary", "X", "--start", "2026-06-10 09:00", "--end", "2026-06-10 09:30",
         "--confirm"]
    )
    out = capsys.readouterr().out
    assert rc == 1  # confirmed but refused by the foreign gate
    assert "confirm_foreign" in out
