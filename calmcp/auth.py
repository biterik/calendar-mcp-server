# Copyright (c) 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>
# Licensed under the PolyForm Noncommercial License 1.0.0 - see LICENSE.md
"""Credential resolution: OS keyring first, hidden runtime prompt as fallback.

Passwords are *never* stored in the repo, in ``calendars.yaml``, or in
environment variables. They live in the OS keyring (macOS Keychain, Windows
Credential Manager, Linux Secret Service). When no keyring backend is available
(e.g. a headless box) we fall back to a hidden terminal prompt; that secret
stays in memory only.
"""
from __future__ import annotations

import getpass
import platform
import subprocess
import sys

from .registry import Account


class AuthError(RuntimeError):
    """Raised when a password cannot be obtained for an account."""


def _keyring_get(service: str, username: str) -> str | None:
    """Fetch a password from the OS keyring, tolerating a missing backend."""
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError:
        return None
    try:
        return keyring.get_password(service, username)
    except KeyringError:
        return None


def _prompt_password(prompt: str) -> str:
    """Ask for a password without echoing it.

    macOS gets a native dialog (works even when launched from a GUI app); every
    platform falls back to a hidden terminal prompt. The secret is never written
    anywhere persistent.
    """
    if platform.system() == "Darwin":
        script = (
            f'display dialog "{prompt}" default answer "" with hidden answer '
            f'buttons {{"Cancel", "OK"}} default button "OK" with title "calmcp"'
        )
        try:
            r = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode == 0:
                for part in r.stdout.strip().split(", "):
                    if part.startswith("text returned:"):
                        return part[len("text returned:") :]
        except (FileNotFoundError, subprocess.SubprocessError):
            pass  # fall through to getpass

    return getpass.getpass(f"{prompt}: ")


def get_password(account: Account, *, allow_prompt: bool = True) -> str:
    """Resolve the password for an account.

    Order: keyring (``keyring_service`` / ``username``) → hidden prompt. Raises
    :class:`AuthError` if nothing is found and prompting is disabled.
    """
    pw = _keyring_get(account.keyring_service, account.username)
    if pw:
        return pw
    hint = (
        f"Store the password in your OS keyring with:\n"
        f"    keyring set {account.keyring_service} {account.username}\n"
        f"(or, if the `keyring` CLI is not on PATH: "
        f"python -m keyring set {account.keyring_service} {account.username})"
    )
    if not allow_prompt:
        raise AuthError(
            f"No password in keyring for service {account.keyring_service!r} / "
            f"user {account.username!r}. {hint}"
        )
    if not sys.stdin.isatty() and platform.system() != "Darwin":
        # Windows / Linux launched without a terminal (e.g. as an MCP subprocess
        # from Claude Desktop): there is no way to prompt, so the keyring must
        # already hold the password.
        raise AuthError(
            f"No password in keyring for service {account.keyring_service!r} / "
            f"user {account.username!r}, and no interactive terminal to prompt on. "
            f"{hint}"
        )
    return _prompt_password(f"Password for {account.username} ({account.id})")


def store_password(account: Account, password: str) -> None:
    """Store a password in the OS keyring under the account's service/username."""
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError as e:
        raise AuthError("The `keyring` package is not installed.") from e
    try:
        keyring.set_password(account.keyring_service, account.username, password)
    except KeyringError as e:
        raise AuthError(f"Could not store password in keyring: {e}") from e
