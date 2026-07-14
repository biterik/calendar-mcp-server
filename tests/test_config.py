# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""Tests for registry-path resolution (``default_registry_path``)."""
from __future__ import annotations

from pathlib import Path

import pytest

from calmcp import registry


def test_env_var_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "custom.yaml"
    f.write_text("accounts: {}\n", encoding="utf-8")
    monkeypatch.setenv("CALMCP_REGISTRY", str(f))
    assert registry.default_registry_path() == f


def test_cwd_before_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CALMCP_REGISTRY", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    local = work / "calendars.yaml"
    local.write_text("accounts: {}\n", encoding="utf-8")
    home = tmp_path / "home"
    (home).mkdir()
    (home / ".calendars.yaml").write_text("accounts: {}\n", encoding="utf-8")
    monkeypatch.chdir(work)
    monkeypatch.setenv("HOME", str(home))
    assert registry.default_registry_path() == local


def test_home_dotfile_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CALMCP_REGISTRY", raising=False)
    work = tmp_path / "empty"
    work.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    dotfile = home / ".calendars.yaml"
    dotfile.write_text("accounts: {}\n", encoding="utf-8")
    monkeypatch.chdir(work)
    monkeypatch.setenv("HOME", str(home))
    assert registry.default_registry_path() == dotfile


def test_xdg_config_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CALMCP_REGISTRY", raising=False)
    work = tmp_path / "empty"
    work.mkdir()
    home = tmp_path / "home"
    cfg = home / ".config" / "calmcp"
    cfg.mkdir(parents=True)
    target = cfg / "calendars.yaml"
    target.write_text("accounts: {}\n", encoding="utf-8")
    monkeypatch.chdir(work)
    monkeypatch.setenv("HOME", str(home))
    assert registry.default_registry_path() == target


def test_missing_returns_first_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CALMCP_REGISTRY", raising=False)
    work = tmp_path / "empty"
    work.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("HOME", str(home))
    # Nothing exists anywhere -> highest-priority candidate (./calendars.yaml).
    assert registry.default_registry_path() == work / "calendars.yaml"


def test_user_config_dir_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(registry.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert registry.user_config_dir() == tmp_path / "Roaming" / "calmcp"


def test_user_config_dir_macos(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(registry.sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert (
        registry.user_config_dir()
        == tmp_path / "Library" / "Application Support" / "calmcp"
    )


def test_user_config_dir_linux_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(registry.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert registry.user_config_dir() == tmp_path / "xdg" / "calmcp"


def test_config_dir_used_in_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CALMCP_REGISTRY", raising=False)
    monkeypatch.setattr(registry.sys, "platform", "win32")
    work = tmp_path / "empty"
    work.mkdir()
    appdata = tmp_path / "Roaming"
    (appdata / "calmcp").mkdir(parents=True)
    target = appdata / "calmcp" / "calendars.yaml"
    target.write_text("accounts: {}\n", encoding="utf-8")
    monkeypatch.chdir(work)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert registry.default_registry_path() == target
