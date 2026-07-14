# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""Pure parsing tests for dates, times, and reminders."""
from __future__ import annotations

import datetime as dt

import pytest

from calmcp import timeparse


def test_parse_endpoint_kinds() -> None:
    assert timeparse.parse_endpoint("2026-06-10")[0] == "date"
    assert timeparse.parse_endpoint("2026-06-10 09:00")[0] == "datetime"
    assert timeparse.parse_endpoint("09:00")[0] == "time"


def test_parse_endpoint_invalid() -> None:
    with pytest.raises(timeparse.TimeParseError):
        timeparse.parse_endpoint("not-a-date")


def test_parse_reminder() -> None:
    assert timeparse.parse_reminder("0") is None
    assert timeparse.parse_reminder(None) is None
    assert timeparse.parse_reminder("30m") == dt.timedelta(minutes=30)
    assert timeparse.parse_reminder("2h") == dt.timedelta(hours=2)
    assert timeparse.parse_reminder("1d") == dt.timedelta(days=1)


def test_resolve_window_all_day() -> None:
    start, end, all_day = timeparse.resolve_window("2026-06-10", "2026-06-12")
    assert all_day is True
    assert start == dt.date(2026, 6, 10)
    # DTEND is exclusive -> last day + 1.
    assert end == dt.date(2026, 6, 13)


def test_resolve_window_timed_applies_timezone() -> None:
    start, end, all_day = timeparse.resolve_window(
        "2026-06-10 09:00", "2026-06-10 10:00", "Europe/Berlin"
    )
    assert all_day is False
    assert isinstance(start, dt.datetime)
    assert start.utcoffset() is not None  # tz attached


def test_resolve_window_force_all_day() -> None:
    start, end, all_day = timeparse.resolve_window(
        "2026-06-10 09:00", "2026-06-10 17:00", all_day=True
    )
    assert all_day is True
    assert start == dt.date(2026, 6, 10)
    assert end == dt.date(2026, 6, 11)


def test_resolve_window_end_before_start() -> None:
    with pytest.raises(timeparse.TimeParseError):
        timeparse.resolve_window("2026-06-10 10:00", "2026-06-10 09:00")
