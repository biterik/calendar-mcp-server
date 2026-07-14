# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""iCalendar parsing and recurrence expansion.

A recurring event is *one* CalDAV resource with an ``RRULE`` — not N events.
With ``expand=True`` we materialise each occurrence in the queried window into
its own row carrying ``uid`` + ``recurrence_id`` (the occurrence's original
start), which is how an LLM "sees" every occurrence. Without expansion a series
collapses to a single master row.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, cast
from zoneinfo import ZoneInfo

import recurring_ical_events
from icalendar import Calendar, Event

# A normalised event row, per DESIGN §6 "Event identity".
EventRow = dict[str, Any]


def _to_iso(value: dt.date | dt.datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _aware_utc(value: dt.date | dt.datetime, tz: ZoneInfo) -> dt.datetime:
    """Normalise a date or (naive/aware) datetime to an aware UTC datetime."""
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)
        return value.astimezone(dt.UTC)
    return dt.datetime(value.year, value.month, value.day, tzinfo=tz).astimezone(
        dt.UTC
    )


def _event_end(comp: Event) -> dt.date | dt.datetime | None:
    """Resolve an event's end from DTEND, or DTSTART + DURATION."""
    dtend = comp.get("dtend")
    if dtend is not None:
        return dtend.dt
    duration = comp.get("duration")
    dtstart = comp.get("dtstart")
    if duration is not None and dtstart is not None:
        return dtstart.dt + duration.dt
    return None


def _text(comp: Event, key: str) -> str | None:
    value = comp.get(key)
    return str(value) if value is not None else None


def event_row(
    comp: Event, calendar_id: str, recurrence_id: str | None = None
) -> EventRow:
    """Convert an iCalendar VEVENT component into a normalised row."""
    dtstart = comp.get("dtstart")
    start_val = dtstart.dt if dtstart is not None else None
    all_day = start_val is not None and not isinstance(start_val, dt.datetime)
    return {
        "calendar_id": calendar_id,
        "uid": _text(comp, "uid"),
        "recurrence_id": recurrence_id,
        "summary": _text(comp, "summary"),
        "start": _to_iso(start_val),
        "end": _to_iso(_event_end(comp)),
        "all_day": all_day,
        "location": _text(comp, "location"),
        "status": _text(comp, "status"),
    }


def extract_vevents(ical_text: str) -> list[Event]:
    """Parse calendar text and return its VEVENT components."""
    cal = Calendar.from_ical(ical_text)
    return [cast(Event, c) for c in cal.walk("VEVENT")]


def _sort_key(row: EventRow) -> tuple[bool, str]:
    start = row.get("start")
    return (start is None, start or "")


def _build_calendar(
    ical_texts: list[str],
) -> tuple[Calendar, dict[str, Event], set[str]]:
    """Combine VEVENTs into one Calendar; track masters and recurring UIDs."""
    combined = Calendar()
    masters: dict[str, Event] = {}
    recurring_uids: set[str] = set()
    for text in ical_texts:
        for comp in extract_vevents(text):
            combined.add_component(comp)
            uid = _text(comp, "uid") or ""
            if comp.get("rrule") is not None or comp.get("rdate") is not None:
                recurring_uids.add(uid)
            if comp.get("recurrence-id") is None:
                masters[uid] = comp
    return combined, masters, recurring_uids


def expand_range(
    ical_texts: list[str],
    range_start: dt.date,
    range_end: dt.date,
    calendar_id: str,
    *,
    expand: bool,
) -> list[EventRow]:
    """Return event rows overlapping ``[range_start, range_end]`` (inclusive).

    ``expand=True`` yields one row per occurrence (with ``recurrence_id`` set on
    members of a recurring series); ``expand=False`` yields one master row per
    series/event that has any occurrence in the window.
    """
    combined, masters, recurring_uids = _build_calendar(ical_texts)

    # recurring_ical_events treats the end as exclusive; +1 day makes the
    # `range_end` day itself inclusive.
    until = range_end + dt.timedelta(days=1)
    occurrences = recurring_ical_events.of(combined).between(range_start, until)

    if expand:
        rows: list[EventRow] = []
        for occ in occurrences:
            uid = _text(occ, "uid") or ""
            recurrence_id = None
            if uid in recurring_uids:
                dtstart = occ.get("dtstart")
                if dtstart is not None:
                    recurrence_id = _to_iso(dtstart.dt)
            rows.append(event_row(occ, calendar_id, recurrence_id=recurrence_id))
        return sorted(rows, key=_sort_key)

    uids_in_range = {(_text(occ, "uid") or "") for occ in occurrences}
    rows = [
        event_row(masters[uid], calendar_id)
        for uid in uids_in_range
        if uid in masters
    ]
    return sorted(rows, key=_sort_key)


def busy_intervals(
    ical_texts: list[str],
    range_start: dt.date,
    range_end: dt.date,
    tzname: str = "Europe/Berlin",
) -> list[tuple[dt.datetime, dt.datetime]]:
    """Return merged busy [start, end) intervals (UTC) within the window.

    Events marked ``TRANSP:TRANSPARENT`` (e.g. multi-day all-day blocks) do not
    contribute to busy time. Output carries no titles/locations — minimal data.
    """
    tz = ZoneInfo(tzname)
    combined, _masters, _recurring = _build_calendar(ical_texts)
    until = range_end + dt.timedelta(days=1)
    occurrences = recurring_ical_events.of(combined).between(range_start, until)

    intervals: list[tuple[dt.datetime, dt.datetime]] = []
    for occ in occurrences:
        if str(occ.get("transp") or "").upper() == "TRANSPARENT":
            continue
        dtstart = occ.get("dtstart")
        end_val = _event_end(occ)
        if dtstart is None or end_val is None:
            continue
        start_utc = _aware_utc(dtstart.dt, tz)
        end_utc = _aware_utc(end_val, tz)
        if end_utc <= start_utc:
            continue
        intervals.append((start_utc, end_utc))

    intervals.sort(key=lambda iv: iv[0])
    merged: list[tuple[dt.datetime, dt.datetime]] = []
    for start_utc, end_utc in intervals:
        if merged and start_utc <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end_utc))
        else:
            merged.append((start_utc, end_utc))
    return merged


def merge_calendars(ical_texts: list[str], prodid: str) -> str:
    """Combine VEVENTs (and VTIMEZONEs) from many resources into one VCALENDAR."""
    out = Calendar()
    out.add("prodid", prodid)
    out.add("version", "2.0")
    seen_tz: set[str] = set()
    for text in ical_texts:
        cal = Calendar.from_ical(text)
        for tzc in cal.walk("VTIMEZONE"):
            tzid = str(tzc.get("tzid") or "")
            if tzid and tzid not in seen_tz:
                seen_tz.add(tzid)
                out.add_component(tzc)
        for comp in cal.walk("VEVENT"):
            out.add_component(comp)
    return out.to_ical().decode("utf-8")


# --------------------------------------------------------------------------- writes

PRODID = "-//calmcp//calmcp//EN"


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _replace(comp: Event, key: str, value: Any) -> None:
    """Replace a single property on a component (pop then add)."""
    if key in comp:
        del comp[key]
    if value is not None:
        comp.add(key, value)


def _set_alarm(ev: Event, reminder: dt.timedelta | None) -> None:
    """Replace VALARM subcomponents with a single DISPLAY alarm (or none)."""
    from icalendar import Alarm

    ev.subcomponents = [c for c in ev.subcomponents if c.name != "VALARM"]
    if reminder is not None:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", str(ev.get("summary") or "Reminder"))
        alarm.add("trigger", -reminder)
        ev.add_component(alarm)


def build_vevent(
    *,
    uid: str,
    summary: str,
    start: dt.date | dt.datetime,
    end: dt.date | dt.datetime,
    all_day: bool,
    location: str | None = None,
    description: str | None = None,
    reminder: dt.timedelta | None = None,
) -> Event:
    """Construct a VEVENT component. ``end`` is exclusive for all-day events."""
    ev = Event()
    ev.add("uid", uid)
    ev.add("summary", summary)
    ev.add("dtstart", start)
    ev.add("dtend", end)
    ev.add("transp", "TRANSPARENT" if all_day else "OPAQUE")
    if location:
        ev.add("location", location)
    if description:
        ev.add("description", description)
    ev.add("dtstamp", _now_utc())
    _set_alarm(ev, reminder)
    return ev


def calendar_text(events: list[Event], prodid: str = PRODID) -> str:
    """Wrap VEVENT component(s) in a VCALENDAR and serialise to text."""
    cal = Calendar()
    cal.add("prodid", prodid)
    cal.add("version", "2.0")
    for ev in events:
        cal.add_component(ev)
    return cal.to_ical().decode("utf-8")


def apply_field_changes(ev: Event, changes: dict[str, Any]) -> None:
    """Apply text/reminder changes to an event component in place.

    Recognised keys: ``summary``, ``location``, ``description``, ``status``
    (value ``None`` clears), and ``reminder`` (a ``timedelta`` or ``None``).
    """
    for key in ("summary", "location", "description", "status"):
        if key in changes:
            _replace(ev, key, changes[key])
    if "reminder" in changes:
        _set_alarm(ev, changes["reminder"])
    _replace(ev, "last-modified", _now_utc())


def master_and_overrides(cal: Calendar) -> tuple[Event | None, dict[str, Event]]:
    """Split a resource's VEVENTs into its master and RECURRENCE-ID overrides."""
    master: Event | None = None
    overrides: dict[str, Event] = {}
    for comp in cal.walk("VEVENT"):
        rid = comp.get("recurrence-id")
        if rid is None:
            master = cast(Event, comp)
        else:
            overrides[rid.dt.isoformat()] = cast(Event, comp)
    return master, overrides


def parse_recurrence_id(
    value: str, like: dt.date | dt.datetime
) -> dt.date | dt.datetime:
    """Parse an occurrence id, matching the date/datetime kind of ``like``."""
    if isinstance(like, dt.datetime):
        return dt.datetime.fromisoformat(value)
    return dt.date.fromisoformat(value[:10])


def find_or_create_override(cal: Calendar, master: Event, recurrence_id: str) -> Event:
    """Return the override VEVENT for an occurrence, creating it from the master."""
    _m, overrides = master_and_overrides(cal)
    if recurrence_id in overrides:
        return overrides[recurrence_id]
    rid = parse_recurrence_id(recurrence_id, master["dtstart"].dt)
    override = Event()
    for key in ("uid", "summary", "location", "description", "transp"):
        if key in master:
            override.add(key, master[key])
    # The override starts at the occurrence instant; preserve the duration.
    override.add("dtstart", rid)
    duration = _event_end(master)
    if duration is not None and "dtstart" in master:
        delta = master["dtend"].dt - master["dtstart"].dt if "dtend" in master else None
        if delta is not None:
            override.add("dtend", rid + delta)
    override.add("recurrence-id", rid)
    override.add("dtstamp", _now_utc())
    cal.add_component(override)
    return override


def add_exdate(master: Event, recurrence_id: str) -> None:
    """Cancel a single occurrence by appending an EXDATE to the master."""
    rid = parse_recurrence_id(recurrence_id, master["dtstart"].dt)
    existing = master.get("exdate")
    values = []
    if existing is not None:
        items = existing if isinstance(existing, list) else [existing]
        for item in items:
            values.extend(item.dts)
    from icalendar.prop import vDDDTypes

    values.append(vDDDTypes(rid))
    if "exdate" in master:
        del master["exdate"]
    master.add("exdate", [v.dt for v in values])


def set_until(master: Event, until: dt.date | dt.datetime) -> None:
    """Bound a master's RRULE with UNTIL (used by thisAndFuture splits)."""
    rrule = master.get("rrule")
    if rrule is None:
        return
    rrule = dict(rrule)
    rrule.pop("COUNT", None)  # COUNT and UNTIL are mutually exclusive.
    rrule["UNTIL"] = [until]
    if "rrule" in master:
        del master["rrule"]
    master.add("rrule", rrule)
