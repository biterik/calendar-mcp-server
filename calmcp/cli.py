# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""``calmcp`` — the command-line interface (the tool's true interface).

Read commands are always safe. Write commands (Phase 3) default to a dry-run and
require ``--confirm``. Every command accepts ``--json`` for machine-readable
output the LLM can consume.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from . import service
from .registry import Registry, RegistryError, default_registry_path, load_registry


def _registry_path(args: argparse.Namespace) -> str:
    if args.registry:
        return args.registry
    return str(default_registry_path())


def _load(args: argparse.Namespace) -> Registry:
    return load_registry(_registry_path(args))


def _parse_date(value: str, field: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise SystemExit(f"--{field} {value!r} is not an ISO date (YYYY-MM-DD).") from None


def _date_range(args: argparse.Namespace) -> tuple[dt.date, dt.date]:
    start = _parse_date(args.from_, "from")
    end = _parse_date(args.to, "to")
    if end < start:
        raise SystemExit(f"--to ({end}) is before --from ({start}).")
    return start, end


def _calendar_ids(args: argparse.Namespace) -> list[str] | None:
    if not args.calendars:
        return None
    return [c.strip() for c in args.calendars.split(",") if c.strip()]


def _emit_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2))


def _has_errors(payload: dict[str, Any]) -> int:
    return 1 if payload.get("errors") else 0


# --------------------------------------------------------------------------- read commands


def cmd_list_calendars(args: argparse.Namespace) -> int:
    reg = _load(args)
    rows = service.list_calendars(reg, account=args.account, probe=not args.offline)
    if args.json:
        _emit_json({"calendars": rows})
        return 0
    if not rows:
        print("No calendars configured.")
        return 0
    for row in rows:
        flag = ""
        if not args.offline:
            flag = "  ✓" if row.get("reachable") else "  ✗"
        name = row.get("live_name") or row.get("name") or ""
        print(f"{row['id']:<20} [{row['role']:<9}] {row['account']:<16} {name}{flag}")
        if row.get("owner"):
            print(f"{'':<20} owner: {row['owner']}")
        if row.get("error"):
            print(f"{'':<20} error: {row['error']}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    reg = _load(args)
    owners = [o.strip() for o in (args.owner or []) if o.strip()]
    result = service.discover_calendars(reg, account=args.account, owners=owners or None)
    if args.json:
        _emit_json(result)
        return 1 if result["errors"] else 0
    cals = result["calendars"]
    if not cals and not result["errors"]:
        print("No calendars discovered.")
    for c in cals:
        print(f"[{c['account']}] {c['name']}  ({c['source']})")
        print(f"    {c['url']}")
    for err in result["errors"]:
        print(f"! {err['account']}: {err['error']}", file=sys.stderr)
    return 1 if result["errors"] else 0


def _print_events(events: list[dict[str, Any]], empty_msg: str) -> None:
    if not events:
        print(empty_msg)
    for ev in events:
        when = ev["start"] or "?"
        if ev["end"]:
            when += f" → {ev['end']}"
        tag = " [all-day]" if ev["all_day"] else ""
        rid = f"  (occ {ev['recurrence_id']})" if ev["recurrence_id"] else ""
        loc = f"  @ {ev['location']}" if ev["location"] else ""
        title = ev["summary"] or "(no title)"
        print(f"{when}{tag}  {title} [{ev['calendar_id']}]{loc}{rid}")


def _print_errors(errors: list[dict[str, str]]) -> None:
    for err in errors:
        print(f"! {err['calendar']}: {err['error']}", file=sys.stderr)


def cmd_query_events(args: argparse.Namespace) -> int:
    reg = _load(args)
    start, end = _date_range(args)
    result = service.query_events(
        reg, start, end, _calendar_ids(args), expand=args.expand
    )
    if args.json:
        _emit_json(result)
        return _has_errors(result)
    _print_events(result["events"], f"No events in {start} … {end}.")
    _print_errors(result.get("errors", []))
    return _has_errors(result)


def cmd_find_events(args: argparse.Namespace) -> int:
    reg = _load(args)
    start, end = _date_range(args)
    result = service.find_events(reg, args.q, start, end, _calendar_ids(args))
    if args.json:
        _emit_json(result)
        return _has_errors(result)
    _print_events(result["events"], f"No events matching {args.q!r} in {start} … {end}.")
    _print_errors(result.get("errors", []))
    return _has_errors(result)


def cmd_get_free_busy(args: argparse.Namespace) -> int:
    reg = _load(args)
    start, end = _date_range(args)
    result = service.get_free_busy(reg, start, end, _calendar_ids(args))
    if args.json:
        _emit_json(result)
        return _has_errors(result)
    if not result["busy"]:
        print(f"Free across {start} … {end} (no busy blocks).")
    for block in result["busy"]:
        print(f"BUSY  {block['start']} → {block['end']}")
    _print_errors(result.get("errors", []))
    return _has_errors(result)


def cmd_export_ics(args: argparse.Namespace) -> int:
    reg = _load(args)
    start, end = _date_range(args)
    result = service.export_ics(reg, start, end, _calendar_ids(args))
    if args.out and args.out != "-":
        Path(args.out).write_text(result["ics"], encoding="utf-8")
        if args.json:
            _emit_json({k: v for k, v in result.items() if k != "ics"} | {"out": args.out})
        else:
            print(f"Wrote {result['event_count']} event(s) to {args.out}")
    else:
        if args.json:
            _emit_json(result)
        else:
            sys.stdout.write(result["ics"])
    _print_errors(result.get("errors", []))
    return _has_errors(result)


# --------------------------------------------------------------------------- write commands


def _print_write(result: dict[str, Any]) -> None:
    state = "DRY-RUN (nothing written)" if result["dryRun"] else "WRITTEN"
    print(f"{result['action']} → {result['calendar']}  [{state}]")
    if result.get("scope"):
        print(f"  scope: {result['scope']}")
    if result.get("uid"):
        print(f"  uid: {result['uid']}")
    if result.get("before"):
        print(f"  before: {json.dumps(result['before'])}")
    if result.get("after"):
        print(f"  after:  {json.dumps(result['after'])}")
    for w in result.get("warnings", []):
        print(f"  ! {w}")
    if result["dryRun"]:
        print("  Re-run with --confirm to apply.")


def _emit_write(args: argparse.Namespace, result: dict[str, Any]) -> int:
    if args.json:
        _emit_json(result)
    else:
        _print_write(result)
    # Non-zero when a confirmed write was refused by the foreign-calendar gate.
    refused = result["dryRun"] and args.confirm
    return 1 if refused else 0


def _parse_set(pairs: list[str] | None) -> dict[str, str]:
    changes: dict[str, str] = {}
    for item in pairs or []:
        if "=" not in item:
            raise SystemExit(f"--set expects key=value, got {item!r}.")
        key, value = item.split("=", 1)
        changes[key.strip()] = value
    return changes


def cmd_create_event(args: argparse.Namespace) -> int:
    reg = _load(args)
    result = service.create_event(
        reg,
        args.calendar,
        args.summary,
        args.start,
        args.end,
        all_day=args.all_day,
        location=args.location,
        description=args.description,
        reminder=args.reminder,
        uid=args.uid,
        confirm=args.confirm,
        confirm_foreign=args.confirm_foreign,
    )
    return _emit_write(args, result)


def cmd_update_event(args: argparse.Namespace) -> int:
    reg = _load(args)
    result = service.update_event(
        reg,
        args.calendar,
        args.uid,
        _parse_set(args.set),
        recurrence_id=args.recurrence_id,
        scope=args.scope,
        confirm=args.confirm,
        confirm_foreign=args.confirm_foreign,
    )
    return _emit_write(args, result)


def cmd_move_event(args: argparse.Namespace) -> int:
    reg = _load(args)
    result = service.move_event(
        reg,
        args.calendar,
        args.uid,
        to_calendar=args.to_calendar,
        start=args.start,
        end=args.end,
        all_day=args.all_day,
        recurrence_id=args.recurrence_id,
        scope=args.scope,
        confirm=args.confirm,
        confirm_foreign=args.confirm_foreign,
    )
    return _emit_write(args, result)


def cmd_delete_event(args: argparse.Namespace) -> int:
    reg = _load(args)
    result = service.delete_event(
        reg,
        args.calendar,
        args.uid,
        recurrence_id=args.recurrence_id,
        scope=args.scope,
        confirm=args.confirm,
        confirm_foreign=args.confirm_foreign,
    )
    return _emit_write(args, result)


# --------------------------------------------------------------------------- parser


def _add_write_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--confirm", action="store_true", help="Actually write (default: dry-run).")
    p.add_argument(
        "--confirm-foreign",
        action="store_true",
        help="Second gate required to write a calendar you do not own.",
    )
    p.add_argument("--json", action="store_true", help="Emit the JSON write contract.")


def _add_range_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--from", dest="from_", required=True, help="Start date (YYYY-MM-DD).")
    p.add_argument("--to", required=True, help="End date, inclusive (YYYY-MM-DD).")
    p.add_argument(
        "--calendars",
        default=None,
        help="Comma-separated calendar ids (default: all configured).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="calmcp", description="CalDAV calendar tooling for LLM-driven workflows."
    )
    parser.add_argument(
        "--registry",
        default=None,
        help=(
            "Path to calendars.yaml. Default search order: $CALMCP_REGISTRY, "
            "./calendars.yaml, ~/.calendars.yaml, ~/.config/calmcp/calendars.yaml."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list_calendars", help="List configured calendars.")
    p_list.add_argument("--account", default=None, help="Only show this account's calendars.")
    p_list.add_argument("--offline", action="store_true", help="No network; print registry.")
    p_list.add_argument("--json", action="store_true", help="Emit JSON.")
    p_list.set_defaults(func=cmd_list_calendars)

    p_disc = sub.add_parser(
        "discover",
        help="List calendars present on the server (to copy into calendars.yaml).",
    )
    p_disc.add_argument("--account", default=None, help="Only probe this account (default: all).")
    p_disc.add_argument(
        "--owner",
        action="append",
        metavar="LOGIN",
        help="Also probe a delegated owner's calendar home (login id). Repeatable.",
    )
    p_disc.add_argument("--json", action="store_true", help="Emit JSON.")
    p_disc.set_defaults(func=cmd_discover)

    p_query = sub.add_parser("query_events", help="List events in a date range.")
    _add_range_args(p_query)
    p_query.add_argument(
        "--expand", action="store_true", help="One row per recurring occurrence."
    )
    p_query.add_argument("--json", action="store_true", help="Emit JSON.")
    p_query.set_defaults(func=cmd_query_events)

    p_find = sub.add_parser("find_events", help="Search events by text in a range.")
    _add_range_args(p_find)
    p_find.add_argument("--q", required=True, help="Substring to match (summary/location).")
    p_find.add_argument("--json", action="store_true", help="Emit JSON.")
    p_find.set_defaults(func=cmd_find_events)

    p_fb = sub.add_parser("get_free_busy", help="Merged busy blocks (minimal data).")
    _add_range_args(p_fb)
    p_fb.add_argument("--json", action="store_true", help="Emit JSON.")
    p_fb.set_defaults(func=cmd_get_free_busy)

    p_exp = sub.add_parser("export_ics", help="Export events in a range to an .ics file.")
    _add_range_args(p_exp)
    p_exp.add_argument("--out", default="-", help="Output file path, or '-' for stdout.")
    p_exp.add_argument("--json", action="store_true", help="Emit JSON metadata.")
    p_exp.set_defaults(func=cmd_export_ics)

    p_create = sub.add_parser("create_event", help="Create an event (dry-run default).")
    p_create.add_argument("--calendar", required=True, help="Target calendar id.")
    p_create.add_argument("--summary", required=True, help="Event title.")
    p_create.add_argument("--start", required=True, help="Start: date or 'date HH:MM'.")
    p_create.add_argument("--end", required=True, help="End: date or 'date HH:MM'.")
    p_create.add_argument("--all-day", action="store_true", help="Force an all-day event.")
    p_create.add_argument("--location", default=None)
    p_create.add_argument("--description", default=None)
    p_create.add_argument("--reminder", default=None, help="0 (off), 30m, 2h, 1d.")
    p_create.add_argument("--uid", default=None, help="Use a specific UID (idempotent upsert).")
    _add_write_args(p_create)
    p_create.set_defaults(func=cmd_create_event)

    p_update = sub.add_parser("update_event", help="Edit event fields (dry-run default).")
    p_update.add_argument("--calendar", required=True, help="Calendar id.")
    p_update.add_argument("--uid", required=True, help="Event UID.")
    p_update.add_argument(
        "--set",
        action="append",
        metavar="KEY=VALUE",
        help="Field to set: summary, location, description, status, reminder. Repeatable.",
    )
    p_update.add_argument("--recurrence-id", dest="recurrence_id", default=None)
    p_update.add_argument(
        "--scope", choices=["this", "all", "thisAndFuture"], default="all"
    )
    _add_write_args(p_update)
    p_update.set_defaults(func=cmd_update_event)

    p_move = sub.add_parser("move_event", help="Change time and/or calendar (dry-run default).")
    p_move.add_argument("--calendar", required=True, help="Source calendar id.")
    p_move.add_argument("--uid", required=True, help="Event UID.")
    p_move.add_argument("--to-calendar", dest="to_calendar", default=None)
    p_move.add_argument("--start", default=None, help="New start: date or 'date HH:MM'.")
    p_move.add_argument("--end", default=None, help="New end: date or 'date HH:MM'.")
    p_move.add_argument("--all-day", action="store_true")
    p_move.add_argument("--recurrence-id", dest="recurrence_id", default=None)
    p_move.add_argument("--scope", choices=["this", "all"], default="all")
    _add_write_args(p_move)
    p_move.set_defaults(func=cmd_move_event)

    p_delete = sub.add_parser("delete_event", help="Delete an event/series (dry-run default).")
    p_delete.add_argument("--calendar", required=True, help="Calendar id.")
    p_delete.add_argument("--uid", required=True, help="Event UID.")
    p_delete.add_argument("--recurrence-id", dest="recurrence_id", default=None)
    p_delete.add_argument(
        "--scope", choices=["this", "all", "thisAndFuture"], default="all"
    )
    _add_write_args(p_delete)
    p_delete.set_defaults(func=cmd_delete_event)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        return int(result) if result is not None else 0
    except RegistryError as e:
        print(f"Registry error: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
