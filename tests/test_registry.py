# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""Registry parsing and validation — no network."""
from __future__ import annotations

import textwrap

import pytest

from calmcp.registry import RegistryError, load_registry, parse_registry

VALID = {
    "accounts": {
        "kerio": {
            "url": "https://host/caldav/users/example.de/e.bitzek",
            "username": "e.bitzek",
            "keyring_service": "calmcp/kerio",
        }
    },
    "calendars": [
        {"id": "personal", "account": "kerio", "role": "owner"},
        {
            "id": "absence",
            "account": "kerio",
            "role": "writable",
            "name": "CM_Absence",
            "owner": "cm-office",
            "url": "https://host/full-calendars/x/cm-office/abc/",
        },
    ],
    "defaults": {"write_calendar": "personal", "timezone": "Europe/Berlin"},
}


def test_parse_valid_registry() -> None:
    reg = parse_registry(VALID)
    assert set(reg.accounts) == {"kerio"}
    assert reg.calendar_ids() == ["personal", "absence"]

    account = reg.accounts["kerio"]
    assert account.verify_ssl is True
    assert account.type == "caldav"

    absence = reg.calendar("absence")
    assert absence.role == "writable"
    assert absence.owner == "cm-office"
    assert reg.account_for(absence) is account

    assert reg.defaults.write_calendar == "personal"
    assert reg.defaults.timezone == "Europe/Berlin"


def test_unknown_calendar_lookup_raises() -> None:
    reg = parse_registry(VALID)
    with pytest.raises(RegistryError):
        reg.calendar("does-not-exist")


def test_invalid_role_rejected() -> None:
    data = {
        "accounts": VALID["accounts"],
        "calendars": [{"id": "x", "account": "kerio", "role": "admin"}],
    }
    with pytest.raises(RegistryError, match="role"):
        parse_registry(data)


def test_calendar_referencing_unknown_account_rejected() -> None:
    data = {
        "accounts": VALID["accounts"],
        "calendars": [{"id": "x", "account": "ghost", "role": "owner"}],
    }
    with pytest.raises(RegistryError, match="unknown account"):
        parse_registry(data)


def test_duplicate_calendar_id_rejected() -> None:
    data = {
        "accounts": VALID["accounts"],
        "calendars": [
            {"id": "dup", "account": "kerio", "role": "owner"},
            {"id": "dup", "account": "kerio", "role": "read-only"},
        ],
    }
    with pytest.raises(RegistryError, match="Duplicate"):
        parse_registry(data)


def test_write_calendar_must_exist() -> None:
    data = {
        "accounts": VALID["accounts"],
        "calendars": [{"id": "x", "account": "kerio", "role": "owner"}],
        "defaults": {"write_calendar": "nope"},
    }
    with pytest.raises(RegistryError, match="write_calendar"):
        parse_registry(data)


def test_missing_account_field_rejected() -> None:
    data = {
        "accounts": {"kerio": {"url": "https://host", "username": "e.bitzek"}},
        "calendars": [{"id": "x", "account": "kerio", "role": "owner"}],
    }
    with pytest.raises(RegistryError, match="keyring_service"):
        parse_registry(data)


def test_no_accounts_rejected() -> None:
    with pytest.raises(RegistryError, match="No accounts"):
        parse_registry({"calendars": [{"id": "x", "account": "k", "role": "owner"}]})


def test_load_registry_from_file(tmp_path) -> None:
    p = tmp_path / "calendars.yaml"
    p.write_text(
        textwrap.dedent(
            """
            accounts:
              kerio:
                url: https://host/caldav/users/example.de/e.bitzek
                username: e.bitzek
                keyring_service: calmcp/kerio
            calendars:
              - id: personal
                account: kerio
                role: owner
            """
        ),
        encoding="utf-8",
    )
    reg = load_registry(p)
    assert reg.calendar_ids() == ["personal"]


def test_load_registry_missing_file(tmp_path) -> None:
    with pytest.raises(RegistryError, match="not found"):
        load_registry(tmp_path / "nope.yaml")
