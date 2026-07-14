# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""CalDAV connection, calendar discovery, and read logic.

Adapted from ``travel-forms-pilot/scripts/add_to_calendar.py``: the Kerio
connection, the owner-home discovery trick for calendars shared *to* you (you
are not the owner), and best-effort display-name resolution. Phase 0 is
read-only — no upsert/delete here yet.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from . import auth
from .registry import Account, CalendarSpec

# `caldav` ships no type stubs, so its objects are typed as ``Any`` here.


class CalDAVError(RuntimeError):
    """Raised on connection or calendar-resolution failures."""


@dataclass
class DiscoveredCalendar:
    """A calendar found on the server during discovery."""

    source: str  # "own" or "shared:<owner>"
    name: str
    url: str
    obj: Any  # caldav.Calendar


def _owner_home_url(account_url: str, owner: str) -> str:
    """Derive another user's calendar-home URL by swapping the login segment.

    e.g. ``https://host/caldav/users/example.org/jdoe`` + owner ``team-office``
    -> ``https://host/caldav/users/example.org/team-office``.
    """
    base = account_url.rstrip("/")
    parent = base.rsplit("/", 1)[0]
    return f"{parent}/{owner}"


def cal_name(c: Any) -> str:
    """Best-effort display name for a caldav.Calendar object."""
    getter = getattr(c, "get_display_name", None)
    if callable(getter):
        try:
            name = getter()
            if name:
                return str(name)
        except Exception:
            pass
    try:
        props = c.get_properties(["{DAV:}displayname"]) or {}
        name = props.get("{DAV:}displayname")
        if name:
            return str(name)
    except Exception:
        pass
    return str(getattr(c, "name", None) or "?")


def connect(account: Account, password: str | None = None) -> Any:
    """Build an authenticated DAVClient for an account.

    The password is taken (in order) from the explicit argument, the OS keyring,
    or a hidden prompt — see :mod:`calmcp.auth`.
    """
    try:
        import caldav
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise CalDAVError("The `caldav` package is not installed.") from e

    if password is None:
        password = auth.get_password(account)
    dav_client: Any = caldav.DAVClient
    return dav_client(
        url=account.url,
        username=account.username,
        password=password,
        ssl_verify_cert=account.verify_ssl,
    )


def discover(
    client: Any, account: Account, owners: tuple[str, ...] = ()
) -> list[DiscoveredCalendar]:
    """List calendars in the account's own home plus any owner-homes.

    ``owners`` are other users' logins (e.g. ``cm-office``) whose homes host
    calendars shared to this account.
    """
    import caldav

    found: list[DiscoveredCalendar] = []
    try:
        for c in client.principal().calendars():
            found.append(DiscoveredCalendar("own", cal_name(c), str(c.url), c))
    except Exception as e:
        raise CalDAVError(f"Could not list calendars for {account.username}: {e}") from e

    for owner in owners:
        owner_home = _owner_home_url(account.url, owner)
        try:
            principal_factory: Any = caldav.Principal
            owner_principal = principal_factory(client=client, url=owner_home)
            for c in owner_principal.calendars():
                found.append(
                    DiscoveredCalendar(f"shared:{owner}", cal_name(c), str(c.url), c)
                )
        except Exception:
            # A missing/forbidden shared home is non-fatal — skip it.
            continue
    return found


def resolve_calendar(
    client: Any, account: Account, spec: CalendarSpec
) -> Any:
    """Resolve a registry calendar spec to a live caldav.Calendar.

    Priority: explicit ``url`` > ``name`` (searched in own + owner home) >
    the principal's first calendar.
    """
    if spec.url:
        return client.calendar(url=spec.url)

    owners = (spec.owner,) if spec.owner else ()
    candidates = discover(client, account, owners)

    if spec.name:
        wanted = spec.name.strip().lower()
        for cand in candidates:
            if cand.name.strip().lower() == wanted:
                return cand.obj
        avail = ", ".join(f"{c.name} [{c.source}]" for c in candidates) or "(none)"
        raise CalDAVError(
            f"Calendar {spec.name!r} (id {spec.id}) not found. Available: {avail}"
        )

    own = [c for c in candidates if c.source == "own"]
    if not own:
        raise CalDAVError(f"No calendars found to resolve {spec.id!r}.")
    return own[0].obj


def fetch_events(
    calendar: Any, start: dt.date, end: dt.date
) -> list[str]:
    """Fetch raw iCalendar text for events overlapping ``[start, end]``.

    The server-side time-range filter handles recurrence overlap; precise
    per-occurrence expansion happens client-side in :mod:`calmcp.ical`.
    """
    start_dt = dt.datetime.combine(start, dt.time.min)
    end_dt = dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min)
    results = calendar.search(start=start_dt, end=end_dt, event=True, expand=False)
    return [str(r.data) for r in results if r.data]


def get_resource(calendar: Any, uid: str) -> Any:
    """Return the CalDAV resource for a UID, or None if absent."""
    try:
        return calendar.event_by_uid(uid)
    except Exception:
        return None


def get_resource_text(calendar: Any, uid: str) -> str | None:
    """Return the raw iCalendar text for a UID, or None if absent."""
    resource = get_resource(calendar, uid)
    return str(resource.data) if resource is not None and resource.data else None


def save_event(calendar: Any, ical_text: str) -> None:
    """UID-based upsert: create the event, or update it if the UID exists."""
    calendar.save_event(ical_text)


def delete_resource(calendar: Any, uid: str) -> bool:
    """Delete the whole resource for a UID. Returns True if something was deleted."""
    resource = get_resource(calendar, uid)
    if resource is None:
        return False
    resource.delete()
    return True
