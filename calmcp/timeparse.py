# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""Parsing of user-supplied dates, times, and reminder specs for writes."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo


class TimeParseError(ValueError):
    """Raised when a date/time/reminder string cannot be parsed."""


def parse_endpoint(value: str) -> tuple[str, dt.datetime | dt.date | dt.time]:
    """Parse a --start/--end value into ('datetime'|'date'|'time', obj)."""
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return "datetime", dt.datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        return "date", dt.date.fromisoformat(value)
    except ValueError:
        pass
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return "time", dt.datetime.strptime(value, fmt).time()
        except ValueError:
            pass
    raise TimeParseError(
        f"Could not parse {value!r}. Use YYYY-MM-DD, 'YYYY-MM-DD HH:MM', or HH:MM."
    )


def parse_reminder(spec: str | None) -> dt.timedelta | None:
    """Parse a reminder spec like '0', '30m', '2h', '1d' into a timedelta or None."""
    if spec is None:
        return None
    s = str(spec).strip().lower()
    if s in ("0", "", "off", "none"):
        return None
    unit = s[-1]
    try:
        n = int(s[:-1]) if unit in "mhd" else int(s)
    except ValueError:
        raise TimeParseError(f"Could not parse reminder {spec!r}. Use 0, 30m, 2h, or 1d.") from None
    if unit == "m":
        return dt.timedelta(minutes=n)
    if unit == "h":
        return dt.timedelta(hours=n)
    return dt.timedelta(days=n)


def resolve_window(
    start_str: str,
    end_str: str,
    tzname: str = "Europe/Berlin",
    *,
    all_day: bool = False,
) -> tuple[dt.date | dt.datetime, dt.date | dt.datetime, bool]:
    """Resolve start/end strings into (dtstart, dtend, all_day).

    For all-day events ``dtend`` is the exclusive day-after the last day. Timed
    events get the registry timezone applied if no offset was given.
    """
    tz = ZoneInfo(tzname)
    s_kind, s_val = parse_endpoint(start_str)
    e_kind, e_val = parse_endpoint(end_str)
    if s_kind == "time" or e_kind == "time":
        raise TimeParseError("Give a full date or date+time for --start/--end (not a bare time).")

    want_all_day = all_day or (s_kind == "date" and e_kind == "date")
    if want_all_day:
        s_date = s_val.date() if isinstance(s_val, dt.datetime) else s_val
        e_date = e_val.date() if isinstance(e_val, dt.datetime) else e_val
        assert isinstance(s_date, dt.date) and isinstance(e_date, dt.date)
        if e_date < s_date:
            raise TimeParseError(f"end date ({e_date}) is before start date ({s_date}).")
        return s_date, e_date + dt.timedelta(days=1), True

    def as_dt(kind: str, val: dt.datetime | dt.date | dt.time) -> dt.datetime:
        if isinstance(val, dt.datetime):
            d = val
        else:
            assert isinstance(val, dt.date)
            d = dt.datetime.combine(val, dt.time.min)
        if d.tzinfo is None:
            d = d.replace(tzinfo=tz)
        return d

    s_dt = as_dt(s_kind, s_val)
    e_dt = as_dt(e_kind, e_val)
    if e_dt <= s_dt:
        raise TimeParseError(f"end ({e_dt}) must be after start ({s_dt}).")
    return s_dt, e_dt, False
