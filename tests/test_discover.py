# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""Tests for server-side calendar discovery (``service.discover_calendars``)."""
from __future__ import annotations

from typing import Any

import pytest

from calmcp import service


def test_discover_lists_server_calendars(writable: tuple[Any, Any]) -> None:
    reg, cal = writable
    result = service.discover_calendars(reg)
    assert result["errors"] == []
    found = {c["url"].rstrip("/") for c in result["calendars"]}
    assert str(cal.url).rstrip("/") in found
    for c in result["calendars"]:
        assert c["account"] == "testacct"
        assert c["name"]
        assert c["url"]
        assert c["source"] == "own"


def test_discover_unknown_account_raises(writable: tuple[Any, Any]) -> None:
    reg, _ = writable
    with pytest.raises(ValueError):
        service.discover_calendars(reg, account="does-not-exist")
