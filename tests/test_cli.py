# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""End-to-end CLI tests against the local Radicale fixture."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from calmcp import cli


def _run_json(capsys: pytest.CaptureFixture[str], argv: list[str]) -> dict:
    rc = cli.main(argv)
    out = capsys.readouterr().out
    return {"rc": rc, "data": json.loads(out)}


def test_list_calendars_offline(
    capsys: pytest.CaptureFixture[str], registry_file: Path
) -> None:
    rc = cli.main(["--registry", str(registry_file), "list_calendars", "--offline", "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert rc == 0
    assert [c["id"] for c in data["calendars"]] == ["work"]
    assert data["calendars"][0]["role"] == "owner"
    # Offline: no reachability probe.
    assert "reachable" not in data["calendars"][0]


def test_list_calendars_probes_server(
    capsys: pytest.CaptureFixture[str], registry_file: Path, memory_keyring: None
) -> None:
    result = _run_json(
        capsys, ["--registry", str(registry_file), "list_calendars", "--json"]
    )
    assert result["rc"] == 0
    cal = result["data"]["calendars"][0]
    assert cal["reachable"] is True
    assert cal["live_name"] == "Test Calendar"


def test_query_events_expanded(
    capsys: pytest.CaptureFixture[str], registry_file: Path, memory_keyring: None
) -> None:
    result = _run_json(
        capsys,
        [
            "--registry",
            str(registry_file),
            "query_events",
            "--from",
            "2026-06-01",
            "--to",
            "2026-06-21",
            "--expand",
            "--json",
        ],
    )
    assert result["rc"] == 0
    events = result["data"]["events"]
    summaries = [e["summary"] for e in events]
    # 3 weekly standups in range + 1 single meeting.
    assert summaries.count("Daily Standup") == 3
    assert summaries.count("Project Sync") == 1
    standups = [e for e in events if e["summary"] == "Daily Standup"]
    assert all(e["recurrence_id"] is not None for e in standups)
    assert all(e["uid"] == "standup-1@test" for e in standups)
    # Sorted by start.
    starts = [e["start"] for e in events]
    assert starts == sorted(starts)


def test_query_events_collapsed_without_expand(
    capsys: pytest.CaptureFixture[str], registry_file: Path, memory_keyring: None
) -> None:
    result = _run_json(
        capsys,
        [
            "--registry",
            str(registry_file),
            "query_events",
            "--from",
            "2026-06-01",
            "--to",
            "2026-06-21",
            "--json",
        ],
    )
    assert result["rc"] == 0
    events = result["data"]["events"]
    standups = [e for e in events if e["summary"] == "Daily Standup"]
    assert len(standups) == 1
    assert standups[0]["recurrence_id"] is None


def test_query_events_empty_range(
    capsys: pytest.CaptureFixture[str], registry_file: Path, memory_keyring: None
) -> None:
    result = _run_json(
        capsys,
        [
            "--registry",
            str(registry_file),
            "query_events",
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-31",
            "--json",
        ],
    )
    assert result["rc"] == 0
    assert result["data"]["events"] == []


def test_query_events_unknown_calendar(
    capsys: pytest.CaptureFixture[str], registry_file: Path
) -> None:
    rc = cli.main(
        [
            "--registry",
            str(registry_file),
            "query_events",
            "--from",
            "2026-06-01",
            "--to",
            "2026-06-02",
            "--calendars",
            "ghost",
        ]
    )
    assert rc == 2
    assert "Unknown calendar id(s): ghost" in capsys.readouterr().err


def test_find_events_matches_summary(
    capsys: pytest.CaptureFixture[str], registry_file: Path, memory_keyring: None
) -> None:
    result = _run_json(
        capsys,
        [
            "--registry",
            str(registry_file),
            "find_events",
            "--from",
            "2026-06-01",
            "--to",
            "2026-06-21",
            "--q",
            "standup",
            "--json",
        ],
    )
    assert result["rc"] == 0
    events = result["data"]["events"]
    assert len(events) == 3
    assert all(e["summary"] == "Daily Standup" for e in events)


def test_find_events_no_match(
    capsys: pytest.CaptureFixture[str], registry_file: Path, memory_keyring: None
) -> None:
    result = _run_json(
        capsys,
        [
            "--registry",
            str(registry_file),
            "find_events",
            "--from",
            "2026-06-01",
            "--to",
            "2026-06-21",
            "--q",
            "nonexistent",
            "--json",
        ],
    )
    assert result["data"]["events"] == []


def test_get_free_busy(
    capsys: pytest.CaptureFixture[str], registry_file: Path, memory_keyring: None
) -> None:
    result = _run_json(
        capsys,
        [
            "--registry",
            str(registry_file),
            "get_free_busy",
            "--from",
            "2026-06-10",
            "--to",
            "2026-06-10",
            "--json",
        ],
    )
    assert result["rc"] == 0
    busy = result["data"]["busy"]
    assert len(busy) == 1
    assert busy[0]["start"].startswith("2026-06-10T09:00:00")
    assert busy[0]["end"].startswith("2026-06-10T10:00:00")
    # Minimal data: no titles leaked.
    assert "summary" not in busy[0]


def test_export_ics_to_file(
    capsys: pytest.CaptureFixture[str],
    registry_file: Path,
    memory_keyring: None,
    tmp_path: Path,
) -> None:
    out = tmp_path / "export.ics"
    rc = cli.main(
        [
            "--registry",
            str(registry_file),
            "export_ics",
            "--from",
            "2026-06-01",
            "--to",
            "2026-06-21",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in text
    assert "standup-1@test" in text
    assert "meeting-1@test" in text


def test_query_events_bad_date_range(registry_file: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(
            [
                "--registry",
                str(registry_file),
                "query_events",
                "--from",
                "2026-06-30",
                "--to",
                "2026-06-01",
            ]
        )
