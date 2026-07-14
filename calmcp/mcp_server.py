# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""MCP adapter — exposes the calmcp operations as MCP tools over stdio.

This is a *thin* adapter: it imports the core library directly (it does not shell
out to the CLI) and forwards to :mod:`calmcp.service`, which returns plain JSON.
The registry is loaded per call (see :func:`calmcp.registry.default_registry_path`:
``$CALMCP_REGISTRY``, then ``./calendars.yaml``, ``~/.calendars.yaml``, or
``~/.config/calmcp/calendars.yaml``) so edits are picked up without a restart.

Write tools default to a dry-run and only act when ``confirm=True`` — the same
safety model as the CLI. Run via the ``calmcp-mcp`` console script.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import service
from .registry import Registry, default_registry_path, load_registry

mcp = FastMCP("calmcp")


def _registry() -> Registry:
    return load_registry(default_registry_path())


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


@mcp.tool()
def list_calendars(account: str | None = None, probe: bool = True) -> list[dict[str, Any]]:
    """List configured calendars with their role + account. ``probe`` checks
    each one is reachable on the server."""
    return service.list_calendars(_registry(), account=account, probe=probe)


@mcp.tool()
def discover(account: str | None = None, owners: list[str] | None = None) -> dict[str, Any]:
    """Enumerate calendars that exist on the server (your own, plus any
    delegated ``owners`` calendar-homes), returning name + url for each. Use
    this to find calendars to add to calendars.yaml. Read-only; changes nothing."""
    return service.discover_calendars(_registry(), account=account, owners=owners)


@mcp.tool()
def query_events(
    from_date: str, to_date: str, calendars: list[str] | None = None, expand: bool = False
) -> dict[str, Any]:
    """Events in the inclusive date range [from_date, to_date] (YYYY-MM-DD).
    Set ``expand`` to return one row per recurring occurrence."""
    return service.query_events(
        _registry(), _date(from_date), _date(to_date), calendars, expand=expand
    )


@mcp.tool()
def find_events(
    q: str, from_date: str, to_date: str, calendars: list[str] | None = None
) -> dict[str, Any]:
    """Search events whose summary or location contains ``q`` within a range."""
    return service.find_events(
        _registry(), q, _date(from_date), _date(to_date), calendars
    )


@mcp.tool()
def get_free_busy(
    from_date: str, to_date: str, calendars: list[str] | None = None
) -> dict[str, Any]:
    """Merged busy intervals across calendars in a range — no titles (minimal data)."""
    return service.get_free_busy(_registry(), _date(from_date), _date(to_date), calendars)


@mcp.tool()
def export_ics(
    from_date: str, to_date: str, calendars: list[str] | None = None
) -> dict[str, Any]:
    """Build a single .ics document for events in a range (returned as text)."""
    return service.export_ics(_registry(), _date(from_date), _date(to_date), calendars)


@mcp.tool()
def create_event(
    calendar: str,
    summary: str,
    start: str,
    end: str,
    all_day: bool = False,
    location: str | None = None,
    description: str | None = None,
    reminder: str | None = None,
    uid: str | None = None,
    confirm: bool = False,
    confirm_foreign: bool = False,
) -> dict[str, Any]:
    """Create an event. Dry-run unless ``confirm=True``; non-owned calendars also
    need ``confirm_foreign=True``. ``start``/``end`` accept 'YYYY-MM-DD' or
    'YYYY-MM-DD HH:MM'. Returns the before/after write contract."""
    return service.create_event(
        _registry(), calendar, summary, start, end,
        all_day=all_day, location=location, description=description,
        reminder=reminder, uid=uid, confirm=confirm, confirm_foreign=confirm_foreign,
    )


@mcp.tool()
def update_event(
    calendar: str,
    uid: str,
    changes: dict[str, str],
    recurrence_id: str | None = None,
    scope: str = "all",
    confirm: bool = False,
    confirm_foreign: bool = False,
) -> dict[str, Any]:
    """Edit event fields (summary/location/description/status/reminder).
    ``scope`` is this|all|thisAndFuture; ``this``/``thisAndFuture`` need
    ``recurrence_id``. Dry-run unless ``confirm=True``."""
    return service.update_event(
        _registry(), calendar, uid, changes,
        recurrence_id=recurrence_id, scope=scope,
        confirm=confirm, confirm_foreign=confirm_foreign,
    )


@mcp.tool()
def move_event(
    calendar: str,
    uid: str,
    to_calendar: str | None = None,
    start: str | None = None,
    end: str | None = None,
    all_day: bool = False,
    recurrence_id: str | None = None,
    scope: str = "all",
    confirm: bool = False,
    confirm_foreign: bool = False,
) -> dict[str, Any]:
    """Change an event's time and/or its calendar. Dry-run unless ``confirm=True``."""
    return service.move_event(
        _registry(), calendar, uid,
        to_calendar=to_calendar, start=start, end=end, all_day=all_day,
        recurrence_id=recurrence_id, scope=scope,
        confirm=confirm, confirm_foreign=confirm_foreign,
    )


@mcp.tool()
def delete_event(
    calendar: str,
    uid: str,
    recurrence_id: str | None = None,
    scope: str = "all",
    confirm: bool = False,
    confirm_foreign: bool = False,
) -> dict[str, Any]:
    """Delete a whole series/event (scope=all) or cancel one occurrence
    (scope=this) or this-and-future (scope=thisAndFuture). Dry-run unless
    ``confirm=True``."""
    return service.delete_event(
        _registry(), calendar, uid,
        recurrence_id=recurrence_id, scope=scope,
        confirm=confirm, confirm_foreign=confirm_foreign,
    )


def main() -> None:
    """Console entry point: run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
