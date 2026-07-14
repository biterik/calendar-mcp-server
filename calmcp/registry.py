# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""Load and validate ``calendars.yaml`` — the account & calendar registry.

The registry carries *no secrets*: passwords live in the OS keyring (see
:mod:`calmcp.auth`). It maps logical calendar ids to accounts and to a safety
``role`` (``owner`` | ``writable`` | ``read-only``) that later phases use to
gate writes.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

VALID_ROLES = ("owner", "writable", "read-only")

REGISTRY_FILENAME = "calendars.yaml"


def user_config_dir() -> Path:
    """The platform-native per-user config directory for calmcp.

    - Windows: ``%APPDATA%\\calmcp``
    - macOS:   ``~/Library/Application Support/calmcp``
    - Linux/other: ``$XDG_CONFIG_HOME/calmcp`` or ``~/.config/calmcp``
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "calmcp"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "calmcp"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "calmcp"


def candidate_registry_paths() -> list[Path]:
    """Locations calmcp looks for the registry, in priority order.

    1. ``$CALMCP_REGISTRY`` (if set)
    2. ``./calendars.yaml`` in the current directory
    3. ``~/.calendars.yaml`` in your home directory
    4. the platform-native config dir (see :func:`user_config_dir`), e.g.
       ``~/.config/calmcp/calendars.yaml`` on Linux,
       ``%APPDATA%\\calmcp\\calendars.yaml`` on Windows.
    """
    paths: list[Path] = []
    env = os.environ.get("CALMCP_REGISTRY")
    if env:
        paths.append(Path(env).expanduser())
    paths.append(Path.cwd() / REGISTRY_FILENAME)
    paths.append(Path.home() / f".{REGISTRY_FILENAME}")
    paths.append(user_config_dir() / REGISTRY_FILENAME)
    # De-duplicate while preserving order (the config dir may coincide with an
    # earlier entry depending on the platform / env).
    seen: set[Path] = set()
    ordered: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def default_registry_path() -> Path:
    """The first registry that exists among :func:`candidate_registry_paths`.

    If none exists, return the highest-priority candidate so callers can show a
    helpful "not found" message pointing at the expected location.
    """
    candidates = candidate_registry_paths()
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


class RegistryError(ValueError):
    """Raised when ``calendars.yaml`` is missing required fields or malformed."""


@dataclass(frozen=True)
class Account:
    """A CalDAV account (a login against one server)."""

    id: str
    url: str
    username: str
    keyring_service: str
    type: str = "caldav"
    verify_ssl: bool = True


@dataclass(frozen=True)
class CalendarSpec:
    """A logical calendar entry mapping to an account + a safety role."""

    id: str
    account: str
    role: str
    name: str | None = None
    url: str | None = None
    owner: str | None = None


@dataclass(frozen=True)
class Defaults:
    """Registry-wide defaults."""

    write_calendar: str | None = None
    timezone: str = "Europe/Berlin"
    reminder: str = "0"


@dataclass
class Registry:
    """The parsed registry: accounts, calendars, and defaults."""

    accounts: dict[str, Account] = field(default_factory=dict)
    calendars: list[CalendarSpec] = field(default_factory=list)
    defaults: Defaults = field(default_factory=Defaults)

    def calendar(self, cal_id: str) -> CalendarSpec:
        for cal in self.calendars:
            if cal.id == cal_id:
                return cal
        known = ", ".join(c.id for c in self.calendars) or "(none)"
        raise RegistryError(f"No calendar with id {cal_id!r}. Known: {known}")

    def account_for(self, cal: CalendarSpec) -> Account:
        try:
            return self.accounts[cal.account]
        except KeyError:
            raise RegistryError(
                f"Calendar {cal.id!r} references unknown account {cal.account!r}."
            ) from None

    def calendar_ids(self) -> list[str]:
        return [c.id for c in self.calendars]


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping or mapping[key] in (None, ""):
        raise RegistryError(f"{where}: missing required field {key!r}.")
    return mapping[key]


def _parse_account(acc_id: str, raw: dict[str, Any]) -> Account:
    where = f"accounts.{acc_id}"
    if not isinstance(raw, dict):
        raise RegistryError(f"{where}: expected a mapping.")
    return Account(
        id=acc_id,
        url=str(_require(raw, "url", where)),
        username=str(_require(raw, "username", where)),
        keyring_service=str(_require(raw, "keyring_service", where)),
        type=str(raw.get("type", "caldav")),
        verify_ssl=bool(raw.get("verify_ssl", True)),
    )


def _parse_calendar(raw: dict[str, Any], index: int) -> CalendarSpec:
    where = f"calendars[{index}]"
    if not isinstance(raw, dict):
        raise RegistryError(f"{where}: expected a mapping.")
    cal_id = str(_require(raw, "id", where))
    account = str(_require(raw, "account", where))
    role = str(raw.get("role", "read-only"))
    if role not in VALID_ROLES:
        raise RegistryError(
            f"{where} ({cal_id}): role {role!r} invalid; use one of {VALID_ROLES}."
        )
    return CalendarSpec(
        id=cal_id,
        account=account,
        role=role,
        name=(str(raw["name"]) if raw.get("name") else None),
        url=(str(raw["url"]) if raw.get("url") else None),
        owner=(str(raw["owner"]) if raw.get("owner") else None),
    )


def _parse_defaults(raw: dict[str, Any]) -> Defaults:
    if not isinstance(raw, dict):
        raise RegistryError("defaults: expected a mapping.")
    return Defaults(
        write_calendar=(str(raw["write_calendar"]) if raw.get("write_calendar") else None),
        timezone=str(raw.get("timezone", "Europe/Berlin")),
        reminder=str(raw.get("reminder", "0")),
    )


def parse_registry(data: dict[str, Any]) -> Registry:
    """Validate an already-loaded mapping into a :class:`Registry`."""
    if not isinstance(data, dict):
        raise RegistryError("Top level of calendars.yaml must be a mapping.")

    raw_accounts = data.get("accounts") or {}
    if not isinstance(raw_accounts, dict):
        raise RegistryError("`accounts` must be a mapping of id -> account.")
    accounts = {acc_id: _parse_account(acc_id, raw) for acc_id, raw in raw_accounts.items()}
    if not accounts:
        raise RegistryError("No accounts defined in calendars.yaml.")

    raw_calendars = data.get("calendars") or []
    if not isinstance(raw_calendars, list):
        raise RegistryError("`calendars` must be a list.")
    calendars = [_parse_calendar(raw, i) for i, raw in enumerate(raw_calendars)]
    if not calendars:
        raise RegistryError("No calendars defined in calendars.yaml.")

    # Cross-reference validation.
    seen: set[str] = set()
    for cal in calendars:
        if cal.id in seen:
            raise RegistryError(f"Duplicate calendar id {cal.id!r}.")
        seen.add(cal.id)
        if cal.account not in accounts:
            raise RegistryError(
                f"Calendar {cal.id!r} references unknown account {cal.account!r}."
            )

    defaults = _parse_defaults(data.get("defaults") or {})
    if defaults.write_calendar and defaults.write_calendar not in seen:
        raise RegistryError(
            f"defaults.write_calendar {defaults.write_calendar!r} is not a known calendar id."
        )

    return Registry(accounts=accounts, calendars=calendars, defaults=defaults)


def load_registry(path: str | Path) -> Registry:
    """Read and validate a ``calendars.yaml`` file."""
    p = Path(path)
    if not p.exists():
        raise RegistryError(
            f"Registry file not found: {p}. Copy calendars.example.yaml to calendars.yaml."
        )
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RegistryError(f"{p}: invalid YAML — {e}") from e
    return parse_registry(data or {})
