# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""Recurrence expansion and event-row normalisation — no network."""
from __future__ import annotations

import datetime as dt

from calmcp import ical

SINGLE_TIMED = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:single-1@test
SUMMARY:Solo Meeting
DTSTART:20260610T090000Z
DTEND:20260610T100000Z
LOCATION:Room 1
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR
"""

ALL_DAY = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:allday-1@test
SUMMARY:Holiday
DTSTART;VALUE=DATE:20260612
DTEND;VALUE=DATE:20260613
END:VEVENT
END:VCALENDAR
"""

WEEKLY = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:weekly-1@test
SUMMARY:Standup
DTSTART:20260601T080000Z
DTEND:20260601T081500Z
RRULE:FREQ=WEEKLY;COUNT=5
END:VEVENT
END:VCALENDAR
"""

JUNE_START = dt.date(2026, 6, 1)
JUNE_END = dt.date(2026, 6, 21)


def test_single_event_row() -> None:
    rows = ical.expand_range([SINGLE_TIMED], JUNE_START, JUNE_END, "cal", expand=True)
    assert len(rows) == 1
    row = rows[0]
    assert row["uid"] == "single-1@test"
    assert row["summary"] == "Solo Meeting"
    assert row["location"] == "Room 1"
    assert row["status"] == "CONFIRMED"
    assert row["all_day"] is False
    assert row["recurrence_id"] is None
    assert row["start"].startswith("2026-06-10T09:00:00")
    assert row["calendar_id"] == "cal"


def test_all_day_detected() -> None:
    rows = ical.expand_range([ALL_DAY], JUNE_START, JUNE_END, "cal", expand=True)
    assert len(rows) == 1
    assert rows[0]["all_day"] is True
    assert rows[0]["start"] == "2026-06-12"


def test_recurrence_expanded_into_occurrences() -> None:
    rows = ical.expand_range([WEEKLY], JUNE_START, JUNE_END, "cal", expand=True)
    # COUNT=5 starting 2026-06-01 weekly -> 06-01, 06-08, 06-15 fall in window.
    starts = [r["start"][:10] for r in rows]
    assert starts == ["2026-06-01", "2026-06-08", "2026-06-15"]
    # Every occurrence carries a recurrence_id (its own start) and shares the UID.
    assert all(r["recurrence_id"] is not None for r in rows)
    assert all(r["uid"] == "weekly-1@test" for r in rows)
    assert rows[0]["recurrence_id"].startswith("2026-06-01")


def test_recurrence_collapsed_without_expand() -> None:
    rows = ical.expand_range([WEEKLY], JUNE_START, JUNE_END, "cal", expand=False)
    assert len(rows) == 1
    assert rows[0]["uid"] == "weekly-1@test"
    assert rows[0]["recurrence_id"] is None


def test_window_excludes_out_of_range_occurrences() -> None:
    # Narrow window catching only the first two standups.
    rows = ical.expand_range(
        [WEEKLY], dt.date(2026, 6, 1), dt.date(2026, 6, 8), "cal", expand=True
    )
    assert [r["start"][:10] for r in rows] == ["2026-06-01", "2026-06-08"]


def test_multiple_calendars_sorted_by_start() -> None:
    rows = ical.expand_range(
        [SINGLE_TIMED, ALL_DAY, WEEKLY], JUNE_START, JUNE_END, "cal", expand=True
    )
    starts = [r["start"] for r in rows]
    assert starts == sorted(starts)
