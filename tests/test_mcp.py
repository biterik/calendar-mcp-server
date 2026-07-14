# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""MCP adapter: tool registration and a live call routed through the service."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from calmcp import mcp_server

EXPECTED_TOOLS = {
    "list_calendars",
    "discover",
    "query_events",
    "find_events",
    "get_free_busy",
    "export_ics",
    "create_event",
    "update_event",
    "move_event",
    "delete_event",
}


def test_all_tools_registered() -> None:
    tools = asyncio.new_event_loop().run_until_complete(mcp_server.mcp.list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOLS


def test_query_events_tool_against_server(
    monkeypatch: pytest.MonkeyPatch, registry_file: Path, memory_keyring: None
) -> None:
    monkeypatch.setenv("CALMCP_REGISTRY", str(registry_file))
    result = mcp_server.query_events("2026-06-01", "2026-06-21", expand=True)
    summaries = [e["summary"] for e in result["events"]]
    assert summaries.count("Daily Standup") == 3
    assert summaries.count("Project Sync") == 1


def test_create_tool_defaults_to_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    radicale_server: str,
    fresh_calendar: object,
    tmp_path: Path,
    memory_keyring: None,
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
                role: owner
                url: {fresh_calendar.url}
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CALMCP_REGISTRY", str(reg_file))
    result = mcp_server.create_event(
        "work", "MCP Event", "2026-06-10 09:00", "2026-06-10 09:30"
    )
    assert result["dryRun"] is True
    # Nothing written.
    after = mcp_server.query_events("2026-06-01", "2026-06-30")
    assert after["events"] == []
