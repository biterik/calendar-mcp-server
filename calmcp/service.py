# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""High-level operations shared by the CLI and the MCP adapter.

Every function takes a :class:`~calmcp.registry.Registry` and returns plain,
JSON-serialisable data (dicts/lists) — no printing, no argparse. The CLI formats
these for humans or dumps them as JSON; the MCP server returns them directly.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, cast

from icalendar import Calendar

from . import audit, caldav_client, ical, timeparse
from .registry import Account, CalendarSpec, Registry

ALLOWED_SET_FIELDS = ("summary", "location", "description", "status", "reminder")
VALID_SCOPES = ("this", "all", "thisAndFuture")


class ClientPool:
    """Lazily connect (once) per account within a single operation."""

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}

    def get(self, account: Account) -> Any:
        if account.id not in self._clients:
            self._clients[account.id] = caldav_client.connect(account)
        return self._clients[account.id]


def select_calendars(
    reg: Registry, account: str | None = None, calendar_ids: list[str] | None = None
) -> list[CalendarSpec]:
    """Resolve a calendar selection from the registry, validating ids."""
    specs = reg.calendars
    if account:
        specs = [c for c in specs if c.account == account]
    if calendar_ids:
        by_id = {c.id: c for c in reg.calendars}
        missing = [cid for cid in calendar_ids if cid not in by_id]
        if missing:
            raise ValueError(f"Unknown calendar id(s): {', '.join(missing)}")
        specs = [by_id[cid] for cid in calendar_ids]
    return specs


def list_calendars(
    reg: Registry,
    account: str | None = None,
    *,
    probe: bool = True,
    pool: ClientPool | None = None,
) -> list[dict[str, Any]]:
    """List configured calendars; with ``probe`` also check reachability."""
    pool = pool or ClientPool()
    rows: list[dict[str, Any]] = []
    for spec in select_calendars(reg, account=account):
        acct = reg.account_for(spec)
        row: dict[str, Any] = {
            "id": spec.id,
            "account": spec.account,
            "role": spec.role,
            "owner": spec.owner,
            "name": spec.name,
            "url": spec.url,
        }
        if probe:
            try:
                cal = caldav_client.resolve_calendar(pool.get(acct), acct, spec)
                row["reachable"] = True
                row["live_name"] = caldav_client.cal_name(cal)
                row["url"] = str(cal.url)
            except Exception as e:
                row["reachable"] = False
                row["error"] = str(e)
        rows.append(row)
    return rows


def discover_calendars(
    reg: Registry,
    account: str | None = None,
    owners: list[str] | None = None,
    *,
    pool: ClientPool | None = None,
) -> dict[str, Any]:
    """Enumerate calendars that actually exist on the server for each account.

    Unlike :func:`list_calendars` (which only reports what's already in the
    registry), this asks the server what calendars the account can see — your
    own plus any delegated ``owners`` homes — returning ``name`` + ``url`` for
    each so you can copy the ones you want into ``calendars.yaml``. Read-only:
    it never modifies anything.
    """
    if account is not None and account not in reg.accounts:
        raise ValueError(f"Unknown account: {account!r}")
    pool = pool or ClientPool()
    accounts = [reg.accounts[account]] if account else list(reg.accounts.values())
    owner_tuple = tuple(owners or ())

    found: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for acct in accounts:
        try:
            client = pool.get(acct)
            for cal in caldav_client.discover(client, acct, owner_tuple):
                found.append(
                    {
                        "account": acct.id,
                        "source": cal.source,
                        "name": cal.name,
                        "url": cal.url,
                    }
                )
        except Exception as e:
            errors.append({"account": acct.id, "error": str(e)})
    return {"calendars": found, "errors": errors}


def _collect_events(
    reg: Registry,
    start: dt.date,
    end: dt.date,
    calendar_ids: list[str] | None,
    *,
    expand: bool,
    pool: ClientPool,
) -> tuple[list[ical.EventRow], list[dict[str, str]]]:
    events: list[ical.EventRow] = []
    errors: list[dict[str, str]] = []
    for spec in select_calendars(reg, calendar_ids=calendar_ids):
        acct = reg.account_for(spec)
        try:
            cal = caldav_client.resolve_calendar(pool.get(acct), acct, spec)
            texts = caldav_client.fetch_events(cal, start, end)
            events.extend(ical.expand_range(texts, start, end, spec.id, expand=expand))
        except Exception as e:
            errors.append({"calendar": spec.id, "error": str(e)})
    events.sort(key=lambda r: (r["start"] is None, r["start"] or ""))
    return events, errors


def query_events(
    reg: Registry,
    start: dt.date,
    end: dt.date,
    calendar_ids: list[str] | None = None,
    *,
    expand: bool = False,
    pool: ClientPool | None = None,
) -> dict[str, Any]:
    """Events in a date range, optionally recurrence-expanded."""
    pool = pool or ClientPool()
    events, errors = _collect_events(
        reg, start, end, calendar_ids, expand=expand, pool=pool
    )
    out: dict[str, Any] = {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "expand": expand,
        "events": events,
    }
    if errors:
        out["errors"] = errors
    return out


def find_events(
    reg: Registry,
    query: str,
    start: dt.date,
    end: dt.date,
    calendar_ids: list[str] | None = None,
    *,
    pool: ClientPool | None = None,
) -> dict[str, Any]:
    """Substring search (summary + location) across calendars in a range."""
    pool = pool or ClientPool()
    events, errors = _collect_events(
        reg, start, end, calendar_ids, expand=True, pool=pool
    )
    needle = query.strip().lower()
    matches = [
        e
        for e in events
        if needle in (e.get("summary") or "").lower()
        or needle in (e.get("location") or "").lower()
    ]
    out: dict[str, Any] = {
        "query": query,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "events": matches,
    }
    if errors:
        out["errors"] = errors
    return out


def get_free_busy(
    reg: Registry,
    start: dt.date,
    end: dt.date,
    calendar_ids: list[str] | None = None,
    *,
    pool: ClientPool | None = None,
) -> dict[str, Any]:
    """Merged busy intervals across calendars — minimal data (no titles)."""
    pool = pool or ClientPool()
    tzname = reg.defaults.timezone
    all_texts: list[str] = []
    errors: list[dict[str, str]] = []
    for spec in select_calendars(reg, calendar_ids=calendar_ids):
        acct = reg.account_for(spec)
        try:
            cal = caldav_client.resolve_calendar(pool.get(acct), acct, spec)
            all_texts.extend(caldav_client.fetch_events(cal, start, end))
        except Exception as e:
            errors.append({"calendar": spec.id, "error": str(e)})

    intervals = ical.busy_intervals(all_texts, start, end, tzname)
    busy = [{"start": s.isoformat(), "end": e.isoformat()} for s, e in intervals]
    out: dict[str, Any] = {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "timezone": tzname,
        "busy": busy,
    }
    if errors:
        out["errors"] = errors
    return out


def export_ics(
    reg: Registry,
    start: dt.date,
    end: dt.date,
    calendar_ids: list[str] | None = None,
    *,
    pool: ClientPool | None = None,
) -> dict[str, Any]:
    """Build a single .ics document for events in a range across calendars."""
    pool = pool or ClientPool()
    all_texts: list[str] = []
    errors: list[dict[str, str]] = []
    count = 0
    for spec in select_calendars(reg, calendar_ids=calendar_ids):
        acct = reg.account_for(spec)
        try:
            cal = caldav_client.resolve_calendar(pool.get(acct), acct, spec)
            texts = caldav_client.fetch_events(cal, start, end)
            all_texts.extend(texts)
            count += sum(len(ical.extract_vevents(t)) for t in texts)
        except Exception as e:
            errors.append({"calendar": spec.id, "error": str(e)})

    ics = ical.merge_calendars(all_texts, prodid="-//calmcp//export//EN")
    out: dict[str, Any] = {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "event_count": count,
        "ics": ics,
    }
    if errors:
        out["errors"] = errors
    return out


# --------------------------------------------------------------------------- writes


def _gate(
    specs: list[CalendarSpec], confirm: bool, confirm_foreign: bool
) -> tuple[list[str], bool]:
    """Compute warnings and whether a write should actually happen.

    A write to any calendar whose role != owner is "foreign": it warns, and on
    ``confirm`` still refuses unless ``confirm_foreign`` is also given.
    """
    warnings: list[str] = []
    foreign = False
    for spec in specs:
        if spec.role != "owner":
            foreign = True
            warnings.append(f"not owner: {spec.id} ({spec.owner or spec.account})")
    blocked = foreign and confirm and not confirm_foreign
    if blocked:
        warnings.append("refused: writing to a non-owned calendar requires confirm_foreign")
    return warnings, bool(confirm and not blocked)


def _finish(
    *,
    action: str,
    calendar_id: str,
    role: str,
    uid: str,
    scope: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    warnings: list[str],
    written: bool,
    commit: Any,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if written:
        commit()
    result: dict[str, Any] = {
        "action": action,
        "dryRun": not written,
        "calendar": calendar_id,
        "role": role,
        "uid": uid,
        "scope": scope,
        "before": before,
        "after": after,
        "warnings": warnings,
    }
    if extra:
        result.update(extra)
    if written:
        audit.append(result)
    return result


def _normalize_changes(raw: dict[str, str]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in ALLOWED_SET_FIELDS:
            raise ValueError(
                f"Cannot set {key!r}; allowed fields: {', '.join(ALLOWED_SET_FIELDS)}"
            )
        if key == "reminder":
            changes[key] = timeparse.parse_reminder(value)
        else:
            changes[key] = value if value != "" else None
    return changes


def _load_resource(
    reg: Registry, calendar_id: str, uid: str, pool: ClientPool
) -> tuple[CalendarSpec, Any, Calendar]:
    spec = reg.calendar(calendar_id)
    acct = reg.account_for(spec)
    cal = caldav_client.resolve_calendar(pool.get(acct), acct, spec)
    text = caldav_client.get_resource_text(cal, uid)
    if text is None:
        raise ValueError(f"No event with uid {uid!r} in calendar {calendar_id!r}.")
    return spec, cal, cast(Calendar, Calendar.from_ical(text))


def create_event(
    reg: Registry,
    calendar_id: str,
    summary: str,
    start: str,
    end: str,
    *,
    all_day: bool = False,
    location: str | None = None,
    description: str | None = None,
    reminder: str | None = None,
    uid: str | None = None,
    confirm: bool = False,
    confirm_foreign: bool = False,
    pool: ClientPool | None = None,
) -> dict[str, Any]:
    """Create an event (dry-run unless ``confirm``). UID-based upsert."""
    pool = pool or ClientPool()
    spec = reg.calendar(calendar_id)
    acct = reg.account_for(spec)
    dtstart, dtend, is_all_day = timeparse.resolve_window(
        start, end, reg.defaults.timezone, all_day=all_day
    )
    reminder_td = timeparse.parse_reminder(reminder)
    uid = uid or f"calmcp-{uuid.uuid4().hex}@calmcp"
    ev = ical.build_vevent(
        uid=uid,
        summary=summary,
        start=dtstart,
        end=dtend,
        all_day=is_all_day,
        location=location,
        description=description,
        reminder=reminder_td,
    )
    after = ical.event_row(ev, calendar_id)
    text = ical.calendar_text([ev])
    warnings, written = _gate([spec], confirm, confirm_foreign)

    def commit() -> None:
        cal = caldav_client.resolve_calendar(pool.get(acct), acct, spec)
        caldav_client.save_event(cal, text)

    return _finish(
        action="create",
        calendar_id=calendar_id,
        role=spec.role,
        uid=uid,
        scope=None,
        before=None,
        after=after,
        warnings=warnings,
        written=written,
        commit=commit,
    )


def update_event(
    reg: Registry,
    calendar_id: str,
    uid: str,
    changes: dict[str, str],
    *,
    recurrence_id: str | None = None,
    scope: str = "all",
    confirm: bool = False,
    confirm_foreign: bool = False,
    pool: ClientPool | None = None,
) -> dict[str, Any]:
    """Edit an event's fields (dry-run unless ``confirm``)."""
    if scope not in VALID_SCOPES:
        raise ValueError(f"scope must be one of {VALID_SCOPES}.")
    pool = pool or ClientPool()
    spec, cal, calobj = _load_resource(reg, calendar_id, uid, pool)
    master, _overrides = ical.master_and_overrides(calobj)
    if master is None:
        raise ValueError(f"Resource {uid!r} has no master VEVENT.")
    field_changes = _normalize_changes(changes)

    if scope == "thisAndFuture":
        return _this_and_future_update(
            reg, spec, cal, calobj, master, uid, recurrence_id, field_changes,
            confirm, confirm_foreign,
        )

    if scope == "this":
        if not recurrence_id:
            raise ValueError("scope=this requires --recurrence-id.")
        target = ical.find_or_create_override(calobj, master, recurrence_id)
        before = ical.event_row(target, calendar_id, recurrence_id=recurrence_id)
        ical.apply_field_changes(target, field_changes)
        after = ical.event_row(target, calendar_id, recurrence_id=recurrence_id)
    else:  # all
        before = ical.event_row(master, calendar_id)
        ical.apply_field_changes(master, field_changes)
        after = ical.event_row(master, calendar_id)

    new_text = calobj.to_ical().decode("utf-8")
    warnings, written = _gate([spec], confirm, confirm_foreign)

    def commit() -> None:
        caldav_client.save_event(cal, new_text)

    return _finish(
        action="update",
        calendar_id=calendar_id,
        role=spec.role,
        uid=uid,
        scope=scope,
        before=before,
        after=after,
        warnings=warnings,
        written=written,
        commit=commit,
    )


def move_event(
    reg: Registry,
    calendar_id: str,
    uid: str,
    *,
    to_calendar: str | None = None,
    start: str | None = None,
    end: str | None = None,
    all_day: bool = False,
    recurrence_id: str | None = None,
    scope: str = "all",
    confirm: bool = False,
    confirm_foreign: bool = False,
    pool: ClientPool | None = None,
) -> dict[str, Any]:
    """Change an event's time and/or its calendar (dry-run unless ``confirm``)."""
    if scope not in ("this", "all"):
        raise ValueError("move_event supports scope this|all.")
    if not (start and end) and not to_calendar:
        raise ValueError("move_event needs --start/--end and/or --to-calendar.")
    pool = pool or ClientPool()
    spec, cal, calobj = _load_resource(reg, calendar_id, uid, pool)
    master, _overrides = ical.master_and_overrides(calobj)
    if master is None:
        raise ValueError(f"Resource {uid!r} has no master VEVENT.")
    before = ical.event_row(master, calendar_id)

    if start and end:
        dtstart, dtend, is_all_day = timeparse.resolve_window(
            start, end, reg.defaults.timezone, all_day=all_day
        )
        target = (
            master
            if scope == "all"
            else ical.find_or_create_override(calobj, master, recurrence_id or "")
        )
        ical._replace(target, "dtstart", dtstart)
        ical._replace(target, "dtend", dtend)
        ical._replace(target, "transp", "TRANSPARENT" if is_all_day else "OPAQUE")

    new_text = calobj.to_ical().decode("utf-8")

    dest_spec = spec
    extra: dict[str, Any] = {}
    specs_to_gate = [spec]
    if to_calendar and to_calendar != calendar_id:
        dest_spec = reg.calendar(to_calendar)
        specs_to_gate = [spec, dest_spec]
        extra["to_calendar"] = to_calendar

    after = ical.event_row(master, dest_spec.id)
    warnings, written = _gate(specs_to_gate, confirm, confirm_foreign)

    def commit() -> None:
        if to_calendar and to_calendar != calendar_id:
            dest_acct = reg.account_for(dest_spec)
            dest_cal = caldav_client.resolve_calendar(pool.get(dest_acct), dest_acct, dest_spec)
            caldav_client.save_event(dest_cal, new_text)
            caldav_client.delete_resource(cal, uid)
        else:
            caldav_client.save_event(cal, new_text)

    return _finish(
        action="move",
        calendar_id=calendar_id,
        role=spec.role,
        uid=uid,
        scope=scope,
        before=before,
        after=after,
        warnings=warnings,
        written=written,
        commit=commit,
        extra=extra,
    )


def delete_event(
    reg: Registry,
    calendar_id: str,
    uid: str,
    *,
    recurrence_id: str | None = None,
    scope: str = "all",
    confirm: bool = False,
    confirm_foreign: bool = False,
    pool: ClientPool | None = None,
) -> dict[str, Any]:
    """Delete a whole series/event or cancel a single occurrence."""
    if scope not in VALID_SCOPES:
        raise ValueError(f"scope must be one of {VALID_SCOPES}.")
    pool = pool or ClientPool()
    spec, cal, calobj = _load_resource(reg, calendar_id, uid, pool)
    master, _overrides = ical.master_and_overrides(calobj)
    if master is None:
        raise ValueError(f"Resource {uid!r} has no master VEVENT.")
    before = ical.event_row(master, calendar_id)
    warnings, written = _gate([spec], confirm, confirm_foreign)

    if scope == "thisAndFuture":
        return _this_and_future_delete(
            reg, spec, cal, calobj, master, uid, recurrence_id, confirm, confirm_foreign
        )

    if scope == "this":
        if not recurrence_id:
            raise ValueError("scope=this requires --recurrence-id.")
        # Drop any override for this occurrence, then EXDATE it on the master.
        calobj.subcomponents = [
            c
            for c in calobj.subcomponents
            if not (
                c.name == "VEVENT"
                and c.get("recurrence-id") is not None
                and c["recurrence-id"].dt.isoformat() == recurrence_id
            )
        ]
        ical.add_exdate(master, recurrence_id)
        new_text = calobj.to_ical().decode("utf-8")
        after = ical.event_row(master, calendar_id)

        def commit() -> None:
            caldav_client.save_event(cal, new_text)
    else:  # all
        after = None

        def commit() -> None:
            caldav_client.delete_resource(cal, uid)

    return _finish(
        action="delete",
        calendar_id=calendar_id,
        role=spec.role,
        uid=uid,
        scope=scope,
        before=before,
        after=after,
        warnings=warnings,
        written=written,
        commit=commit,
    )


def _this_and_future_update(
    reg: Registry,
    spec: CalendarSpec,
    cal: Any,
    calobj: Calendar,
    master: Any,
    uid: str,
    recurrence_id: str | None,
    field_changes: dict[str, Any],
    confirm: bool,
    confirm_foreign: bool,
) -> dict[str, Any]:
    """Split a series at ``recurrence_id``: bound the old master, create a new
    master carrying the edits for this-and-future occurrences (Phase 4)."""
    new_master, before, after = _split_series(
        reg, spec, calobj, master, recurrence_id, field_changes
    )
    old_text = calobj.to_ical().decode("utf-8")
    new_text = ical.calendar_text([new_master])
    warnings, written = _gate([spec], confirm, confirm_foreign)

    def commit() -> None:
        caldav_client.save_event(cal, old_text)
        caldav_client.save_event(cal, new_text)

    return _finish(
        action="update",
        calendar_id=spec.id,
        role=spec.role,
        uid=uid,
        scope="thisAndFuture",
        before=before,
        after=after,
        warnings=warnings,
        written=written,
        commit=commit,
        extra={"new_uid": str(new_master["uid"])},
    )


def _this_and_future_delete(
    reg: Registry,
    spec: CalendarSpec,
    cal: Any,
    calobj: Calendar,
    master: Any,
    uid: str,
    recurrence_id: str | None,
    confirm: bool,
    confirm_foreign: bool,
) -> dict[str, Any]:
    """Delete this-and-future occurrences by bounding the master's RRULE."""
    if not recurrence_id:
        raise ValueError("scope=thisAndFuture requires --recurrence-id.")
    if master.get("rrule") is None:
        raise ValueError("thisAndFuture only applies to recurring events.")
    rid = ical.parse_recurrence_id(recurrence_id, master["dtstart"].dt)
    until = _until_before(rid)
    before = ical.event_row(master, spec.id)
    ical.set_until(master, until)
    new_text = calobj.to_ical().decode("utf-8")
    after = ical.event_row(master, spec.id)
    warnings, written = _gate([spec], confirm, confirm_foreign)

    def commit() -> None:
        caldav_client.save_event(cal, new_text)

    return _finish(
        action="delete",
        calendar_id=spec.id,
        role=spec.role,
        uid=uid,
        scope="thisAndFuture",
        before=before,
        after=after,
        warnings=warnings,
        written=written,
        commit=commit,
    )


def _until_before(rid: dt.date | dt.datetime) -> dt.date | dt.datetime:
    """The UNTIL bound that excludes the occurrence at ``rid`` and everything after."""
    if isinstance(rid, dt.datetime):
        return rid - dt.timedelta(seconds=1)
    return rid - dt.timedelta(days=1)


def _split_series(
    reg: Registry,
    spec: CalendarSpec,
    calobj: Calendar,
    master: Any,
    recurrence_id: str | None,
    field_changes: dict[str, Any],
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """Bound the existing master with UNTIL and build a new master for the tail."""
    if not recurrence_id:
        raise ValueError("scope=thisAndFuture requires --recurrence-id.")
    if master.get("rrule") is None:
        raise ValueError("thisAndFuture only applies to recurring events.")
    rid = ical.parse_recurrence_id(recurrence_id, master["dtstart"].dt)
    before = ical.event_row(master, spec.id)

    # Capture the original RRULE before bounding the old series (set_until edits
    # it in place, which would otherwise leak the UNTIL into the new master).
    original_rrule = dict(master["rrule"])

    # Bound the old series to end before the split point.
    ical.set_until(master, _until_before(rid))

    # New master: a copy of the original starting at the split, with edits.
    new_master = ical.Event()
    for key in ("summary", "location", "description", "transp"):
        if key in master:
            new_master.add(key, master[key])
    new_master.add("rrule", original_rrule)
    new_master.add("uid", f"calmcp-{uuid.uuid4().hex}@calmcp")
    new_master.add("dtstart", rid)
    if "dtstart" in master and "dtend" in master:
        delta = master["dtend"].dt - master["dtstart"].dt
        new_master.add("dtend", rid + delta)
    new_master.add("dtstamp", ical._now_utc())
    ical.apply_field_changes(new_master, field_changes)
    after = ical.event_row(new_master, spec.id)
    return new_master, before, after
