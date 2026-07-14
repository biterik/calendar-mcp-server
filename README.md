# calendar-mcp-server (`calmcp`)

_By Erik Bitzek <e.bitzek@mpi-susmat.de> — licensed under [PolyForm Noncommercial 1.0.0](LICENSE.md)_

A thin, privacy-respecting **CalDAV toolkit** that lets an LLM read and manage your
calendars — safely. The intelligence lives in the LLM and a small set of skill
prompts; the tool itself is a compact set of well-guarded primitives with
dry-run writes, role gating, and an audit log.

Works with any CalDAV server (Kerio Connect, Apple **iCloud**, Nextcloud,
Radicale, Fastmail, …). Exposes everything over the **Model Context Protocol
(MCP)** so it plugs straight into Claude Desktop, Claude Code, and Cowork.

> **Status.** Read commands (`list_calendars`, `discover`, `query_events`,
> `find_events`, `get_free_busy`, `export_ics`) and write commands
> (`create_event`, `update_event`, `move_event`, `delete_event` — dry-run by
> default) are implemented, plus the MCP adapter and LLM skills. Google (via its
> own API) is deferred; see [DESIGN.md](DESIGN.md).

## Why this design

- **No secrets in the repo.** Passwords never live in the code, in
  `calendars.yaml`, or in environment variables — they're stored in your OS
  keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service).
- **Writes are safe by default.** Every write is a `--confirm`-gated dry-run
  that prints a `before`/`after` diff first. Writing to a calendar you don't own
  needs a second `--confirm-foreign` gate. Every real write is appended to an
  audit log.
- **Least privilege.** A small YAML registry maps friendly calendar ids to
  accounts and a safety `role` (`owner` / `writable` / `read-only`).
- **LLM-friendly.** Ships with skill prompts (`skills/`) so an assistant can
  turn free-text dates into events, do bulk edits, and check overlaps.

## Quick start

```bash
# 1. Install
git clone https://github.com/biterik/calendar-mcp-server.git
cd calendar-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[mcp]"            # add ,dev for tests/lint: ".[mcp,dev]"

# 2. Create your registry (copy the example; it is git-ignored)
cp calendars.example.yaml calendars.yaml
$EDITOR calendars.yaml

# 3. Store each account's password in your OS keyring (never in the repo)
keyring set calmcp/kerio_personal your-username     # prompts, hidden input

# 4. Find your real calendars and paste the ones you want into calendars.yaml
calmcp discover

# 5. Check everything is reachable
calmcp list_calendars
```

> **Windows / Linux.** Use `python` instead of `python3` on Windows, and activate
> the venv with `.venv\Scripts\Activate.ps1` (PowerShell) or
> `.venv\Scripts\activate.bat` (cmd). On Linux/macOS use
> `source .venv/bin/activate` as shown. Everything else is identical across
> platforms — `calmcp` works the same on all three.

## Configuration

### Where the registry lives

`calmcp` looks for your `calendars.yaml` in this order and uses the first it finds:

1. `$CALMCP_REGISTRY` (an explicit path)
2. `./calendars.yaml` (the current directory)
3. `~/.calendars.yaml` (per-user; works on every platform)
4. the platform-native config directory:
   - **Linux:** `~/.config/calmcp/calendars.yaml` (or `$XDG_CONFIG_HOME/calmcp/…`)
   - **macOS:** `~/Library/Application Support/calmcp/calendars.yaml`
   - **Windows:** `%APPDATA%\calmcp\calendars.yaml`

To run `calmcp` from anywhere, put your file in that config directory (or use
`~/.calendars.yaml`). You can always override with `--registry
path/to/calendars.yaml` or `CALMCP_REGISTRY=...`.

`calendars.yaml` is **git-ignored**, so it never ends up in the repo and a
`git pull` will never overwrite it. Only `calendars.example.yaml` is tracked.

### The registry file

It maps calendar ids → accounts → roles. No passwords — those go in the keyring.

```yaml
accounts:
  kerio_personal:
    type: caldav
    url: "https://caldav.example.de/caldav/users/example.de/jdoe"
    username: jdoe
    keyring_service: "calmcp/kerio_personal"
    verify_ssl: true

  icloud:
    type: caldav
    url: "https://caldav.icloud.com"
    username: "your-apple-id@icloud.com"
    keyring_service: "calmcp/icloud"      # Apple APP-SPECIFIC password

calendars:
  - id: me_personal            # you own this one
    account: kerio_personal
    role: owner

  - id: family                 # shared to you, read-only
    account: icloud
    name: "Family"
    role: read-only

defaults:
  write_calendar: me_personal
  timezone: Europe/Berlin
```

### Credentials (OS keyring)

Passwords live in your operating system's credential store — never in the repo:
**macOS** Keychain, **Windows** Credential Manager, **Linux** Secret Service
(GNOME Keyring / KWallet, via libsecret). Set one with:

```bash
keyring set <keyring_service> <username>       # e.g. keyring set calmcp/icloud you@icloud.com
# If the `keyring` command isn't on PATH (common on Windows):
python -m keyring set <keyring_service> <username>
```

**Headless Linux note.** The Secret Service needs a running desktop / D-Bus
session. On a server — or if you see "No recommended backend" — install an
alternative backend (`pip install keyrings.alt`) or run inside an unlocked
keyring session. Because the MCP server is launched without a terminal, the
password must already be in the keyring before you start your Claude client
(there's nowhere to prompt).

### iCloud

iCloud is just another CalDAV account. Use `https://caldav.icloud.com` and an
**app-specific password** (generate one at
[appleid.apple.com](https://appleid.apple.com) → Sign-In & Security):

```bash
keyring set calmcp/icloud your-apple-id@icloud.com   # paste the app-specific password
```

### Finding calendars with `discover`

Instead of hunting for CalDAV URLs by hand, ask the server:

```bash
calmcp discover                       # all configured accounts
calmcp discover --account icloud      # just one account
calmcp discover --owner cm-office     # also probe a calendar shared TO you
```

It prints the real `name` and `url` of every calendar it can see. Copy the URL
of the one you want into `calendars.yaml` as a new entry. `discover` is
read-only and never changes anything.

## Command-line usage

```bash
# Read:
calmcp list_calendars
calmcp query_events --from 2026-06-01 --to 2026-06-30
calmcp query_events --from 2026-06-01 --to 2026-06-30 --calendars me_personal --json
calmcp find_events   --from 2026-06-01 --to 2026-12-31 --q "DFG"
calmcp get_free_busy --from 2026-06-14 --to 2026-06-21
calmcp export_ics    --from 2026-06-01 --to 2026-06-30 --out june.ics
```

### Writing events (safe by default)

Write commands print a dry-run diff and do **nothing** until you add `--confirm`:

```bash
# Preview only — writes nothing:
calmcp create_event --calendar me_personal --summary "Dentist" \
    --start "2026-07-01 09:00" --end "2026-07-01 09:30"

# Actually create it:
calmcp create_event --calendar me_personal --summary "Dentist" \
    --start "2026-07-01 09:00" --end "2026-07-01 09:30" --confirm

calmcp update_event --calendar me_personal --uid <uid> --set location="Room 2" --confirm
calmcp move_event   --calendar me_personal --uid <uid> \
    --start "2026-07-01 10:00" --end "2026-07-01 10:30" --confirm
calmcp delete_event --calendar me_personal --uid <uid> --confirm
```

Writing to a calendar whose `role` isn't `owner` adds a warning and requires a
second `--confirm-foreign` gate. Recurring writes take `--scope this|all|thisAndFuture`.
Every real write is appended to an audit log — `~/.local/state/calmcp/audit.jsonl`
on Linux/macOS, `%LOCALAPPDATA%\calmcp\audit.jsonl` on Windows (override with
`CALMCP_STATE_DIR`).

## Connect to Claude (MCP)

`calmcp` exposes these tools over MCP (stdio):

| Tool | What it does |
|------|--------------|
| `list_calendars` | List configured calendars, roles, and reachability |
| `discover` | List calendars present on the server (to add to the registry) |
| `query_events` | List events in a date range (optionally expand recurrences) |
| `find_events` | Full-text search across calendars in a range |
| `get_free_busy` | Free/busy blocks for a range |
| `export_ics` | Export a range to iCalendar (`.ics`) |
| `create_event` | Create an event (dry-run unless confirmed) |
| `update_event` | Change fields on an event |
| `move_event` | Reschedule an event |
| `delete_event` | Delete an event |

The MCP server finds its registry the same way the CLI does (see
[Where the registry lives](#where-the-registry-lives)). Because your client
launches the server from an arbitrary working directory, set `CALMCP_REGISTRY`
to an **absolute path** (or keep your file at `~/.config/calmcp/calendars.yaml`).

### Claude Desktop

Edit the config file — macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`; Windows:
`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "calmcp": {
      "command": "/path/to/calendar-mcp-server/.venv/bin/calmcp-mcp",
      "env": {
        "CALMCP_REGISTRY": "/path/to/calendar-mcp-server/calendars.yaml"
      }
    }
  }
}
```

Fully quit and reopen Claude Desktop; the `calmcp` tools appear in a new chat.

On **Windows**, the launcher is `calmcp-mcp.exe` under `Scripts`, and JSON
requires **escaped backslashes**:

```json
{
  "mcpServers": {
    "calmcp": {
      "command": "C:\\Users\\you\\calendar-mcp-server\\.venv\\Scripts\\calmcp-mcp.exe",
      "env": {
        "CALMCP_REGISTRY": "C:\\Users\\you\\calendar-mcp-server\\calendars.yaml"
      }
    }
  }
}
```

(Tip: put your registry at the platform config path above and you can drop the
`CALMCP_REGISTRY` env entirely.)

### Claude Code

```bash
claude mcp add calmcp \
  --env CALMCP_REGISTRY=/path/to/calendar-mcp-server/calendars.yaml \
  -- /path/to/calendar-mcp-server/.venv/bin/calmcp-mcp
```

### Skills

The prompts in [`skills/`](skills/) (`dates-to-events`, `bulk-edit`,
`overlap-check`) teach an assistant common calendar workflows on top of these
tools.

## Updating

Because your `calendars.yaml` and keyring passwords live outside the repo,
updating is just:

```bash
git pull
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e ".[mcp]"             # in case dependencies changed
```

Your registry and credentials are untouched. If you moved your registry to
`~/.config/calmcp/calendars.yaml`, you can even delete and re-clone the repo
without losing your setup.

## Develop

```bash
pip install -e ".[mcp,dev]"
ruff check .
mypy calmcp
pytest
```

Tests run against a local [Radicale](https://radicale.org/) CalDAV fixture — no
real credentials, and no network calls to any real provider.

## License

Copyright © 2026 Erik Bitzek <e.bitzek@mpi-susmat.de>.

Released under the **[PolyForm Noncommercial License 1.0.0](LICENSE.md)** — free
to use, modify, and share for any **noncommercial** purpose (personal projects,
research, education, and other noncommercial organizations). Commercial use
requires a separate license from the author.
