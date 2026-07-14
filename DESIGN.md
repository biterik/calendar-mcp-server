# calendar-mcp-server — Design
_Author: Erik Bitzek <e.bitzek@mpi-susmat.de> - PolyForm Noncommercial License 1.0.0_

**Status:** design, pre-implementation. **Date:** 16 June 2026.
A portable, privacy-respecting tool that lets an LLM (Claude, GWDG, or any
agent) read and manage several calendars over CalDAV. All workflow
intelligence lives in the LLM + skill prompts; the tool itself is a thin,
well-guarded set of primitives.

---

## 1. Purpose & scope

Let an LLM help manage the user's calendars:

- **2× Kerio Connect** calendars (some shared; the user is not always the
  owner — e.g. `CM_Absence` owned by `cm-office`, write access granted).
- **Apple / iCloud** calendars (via iCloud CalDAV).
- **Google** calendars — *deferred / optional* (Google's CalDAV is weak; would
  need its API).

Two headline workflows, both driven by the LLM (not the tool):

1. **Dates/PDF → events.** Paste a list of dates or a PDF; the LLM proposes
   calendar entries (name, location, time/all-day, reminder, suggested
   calendar), asks for missing info, shows a review table, and on confirmation
   writes them. Can also emit an `.ics` for sharing.
2. **Overlap check.** For one or more dates, report conflicts and context
   across all calendars: same day, **day before**, **day after**, and the
   **week after** (looming conferences/deadlines).

Plus primitives the LLM composes: create/update/move/delete events, list
calendars, find events, bulk edits, free/busy.

## 2. Non-goals

- No scheduling/AI logic inside the tool. No NLP, no PDF parsing in the tool —
  the LLM does that and calls primitives.
- No always-on network service exposed to the internet. The tool runs locally;
  the LLM (local or remote API) only ever sees tool **text output**.
- No iTIP/invitation sending in v1 (RSVP/attendee email is out of scope).

## 3. Architecture

```
          ┌─────────────────────────────────────────────┐
          │  core library  (calmcp/)                     │
          │  CalDAV client · auth (keyring) · iCal model │
          │  recurrence · calendar registry · audit log  │
          └───────────────┬──────────────┬──────────────┘
                          │              │
                 ┌────────▼───────┐  ┌───▼─────────────┐
                 │  CLI  `calmcp` │  │  MCP adapter     │
                 │  (true iface)  │  │  (mcp server)    │
                 └────────┬───────┘  └───┬─────────────┘
                          │              │
       any agent that can │              │ MCP-capable clients
       run shell commands │              │ (Claude Desktop/Code/Cowork)
   (Claude Code, a local  │              │
    agent pointed at GWDG)│              │
```

**Key principle:** the **CLI is the real interface**; the MCP server is one
thin adapter over it. This is what makes the tool *and* the skills portable:
not every LLM front-end (e.g. GWDG Chat AI) is an MCP client, but any agent
that can run a command can use the CLI. Skills are markdown prompts that work
with either.

**"Switchable LLM" is done by switching the model the *local* agent calls** —
not by exposing the server to a remote host. The write-capable server always
stays on the user's machine.

**Language/stack:** Python 3.11+. Libraries: `caldav`, `icalendar`,
`keyring`, `pyyaml`, `mcp` (for the adapter), `click`/`argparse` for the CLI.
Reuses the proven logic from `travel-forms-pilot/scripts/add_to_calendar.py`
(Kerio auth workaround, UID upsert, shared-calendar discovery, dry-run).

## 4. Account & calendar model

A git-ignored `calendars.yaml` (no secrets — passwords live in the OS keyring):

```yaml
accounts:
  kerio_personal:
    type: caldav
    url: "https://xmail1.example.de/caldav/users/example.de/jdoe"
    username: jdoe
    keyring_service: "calmcp/kerio_personal"   # password pulled from OS keyring
    verify_ssl: true
  icloud:
    type: caldav
    url: "https://caldav.icloud.com"
    username: "<apple-id>"
    keyring_service: "calmcp/icloud"           # Apple APP-SPECIFIC password

calendars:
  - id: me_personal
    account: kerio_personal
    role: owner                                # owner | writable | read-only
  - id: cm_absence
    account: kerio_personal
    name: "CM_Absence - cm-office"
    url: "https://xmail1.example.de/full-calendars/example.org/cm-office/C4.../"
    role: writable
    owner: cm-office
  - id: family
    account: icloud
    role: read-only

defaults:
  write_calendar: me_personal
  timezone: Europe/Berlin
  reminder: "0"            # 0=off, or 30m / 2h / 1d
```

`role` is the safety lever: writes to `writable`/`owner` you-own calendars are
routine; writes to anything you don't own require explicit confirmation and are
always logged.

`calmcp discover --account <id>` lists the calendars an account exposes (reuses
the owner-home discovery trick) so the user can paste them in with roles.

## 5. Credentials

- Passwords/app-passwords stored via **`keyring`** → macOS Keychain, Windows
  Credential Manager, Linux Secret Service (libsecret). **Never** in the repo,
  never in env, never in `calendars.yaml`.
- `calmcp login --account <id>` prompts once (hidden) and stores the secret in
  the keyring under `keyring_service`.
- Kerio note: AD accounts can't use Kerio app passwords (KADE bug) → store the
  **regular** your Kerio password in the keyring. iCloud requires an **app-specific
  password** generated at appleid.apple.com (Apple ID has 2FA).
- Fallback when no keyring backend exists (headless Linux): hidden runtime
  prompt, like the current script. Secret stays in memory only.

## 6. Tool surface (CLI = MCP tools)

All commands accept `--json` and emit machine-readable JSON for the LLM. Read
commands are always safe; write commands default to **dry-run**.

| CLI / MCP tool | Purpose | Key args |
|---|---|---|
| `list_calendars` | All calendars + role + account | `--account` |
| `query_events` | Events in a range, **recurrence-expanded** | `--from --to --calendars --q --expand` |
| `find_events` | Search across calendars (for bulk ops) | `--q --from --to --calendars` |
| `get_free_busy` | Busy/free blocks (minimal data) | `--from --to --calendars` |
| `create_event` | Create (dry-run default) | `--calendar --summary --start --end --all-day --location --reminder --confirm` |
| `update_event` | Edit one/series (dry-run default) | `--calendar --uid --recurrence-id --scope --set ... --confirm` |
| `move_event` | Change time and/or calendar | `--uid --to-calendar --start --end --confirm` |
| `delete_event` | Delete (dry-run default) | `--calendar --uid --recurrence-id --scope --confirm` |
| `export_ics` | Write `.ics` for given events/range | `--from --to --calendars --out` |
| `import_ics` | Parse an `.ics` into event proposals | `--file` |

**Event identity** returned by reads: `{calendar_id, uid, recurrence_id?,
summary, start, end, all_day, location, status}`. Writes are addressed by
`(calendar_id, uid[, recurrence_id])`. UID is stable → re-create updates,
never duplicates.

**Output contract** (every write, dry-run or real):
```json
{ "action":"update", "dryRun":true, "calendar":"cm_absence",
  "role":"writable", "uid":"...", "scope":"this",
  "before":{...}, "after":{...}, "warnings":["not owner: cm-office"] }
```

## 7. Recurrence model

A recurring event is **one CalDAV resource** with an `RRULE`, not N events.

- **Reads** with `--expand` return each occurrence as a row carrying `uid` +
  `recurrence_id` (the occurrence's original start). This is how the LLM "sees
  all occurrences up to 3 years" and lists them.
- **Writes** take `--scope`:
  - `this` → override a single occurrence (`RECURRENCE-ID`). Easy.
  - `all` → edit the master (`RRULE`). Easy.
  - `thisAndFuture` → split the series (UNTIL on old master + new master). The
    only fiddly case → if the backend can't do it cleanly, the tool **refuses
    and tells the user to do it in the calendar app** (explicit, never a silent
    mess). v1 may implement only `this` + `all` and punt `thisAndFuture`.
- Guardrail: the tool rejects "write each expanded instance as if independent"
  (they share a UID). Bulk edits go through `find_events` → per-result
  `update_event(scope=this)`, which is correct and idempotent.

## 8. Write-safety model

1. **Dry-run by default.** Nothing is written without `--confirm`. The dry-run
   prints `before`/`after`.
2. **Role-gated confirmation.** Writes to a calendar whose `role != owner`
   carry a `warnings` entry and, in interactive/MCP use, require an explicit
   second confirmation. The LLM is instructed (skill) to surface these.
3. **Idempotent UID upsert** — re-running updates the same event.
4. **Audit log.** Every real write appends a JSONL line (timestamp, action,
   calendar, uid, summary, before/after) to `~/.local/state/calmcp/audit.jsonl`
   (XDG; platform-appropriate). Enables review and manual undo.
5. **No bulk writes without enumeration.** Bulk ops must first `find_events`,
   show the list, then write item-by-item.

## 9. Skills (LLM-side, transferable)

Markdown prompts in `skills/`, usable by any LLM/agent (MCP or CLI):

- `skills/dates-to-events.md` — Parse pasted dates / an attached PDF → build a
  proposal table (summary, location, start/end or all-day, reminder, suggested
  `calendar_id` based on `defaults` + content), ask for gaps in one batched
  question, show the table, on "yes" call `create_event --confirm` per row;
  optionally `export_ics` for sharing.
- `skills/overlap-check.md` — For each target date, call `query_events` (or
  `get_free_busy` for minimal exposure) over [date-1 … date+7] across all
  calendars; report same-day conflicts + day-before + day-after + week-after
  context, flagging conferences/deadlines.
- `skills/bulk-edit.md` — `find_events` → present list → per-item
  `update_event`/`move_event` with `scope`.

Skills also carry the privacy guidance (below) so the LLM minimizes what it
sends to a remote model.

## 10. MCP adapter

A small `mcp` server exposing each CLI command as a tool with a JSON schema
matching §6. It imports the core library directly (not by shelling out). Ships
as `calmcp-mcp` console entry point; configured in a client's MCP settings to
run locally over stdio.

## 11. Privacy & security model

- **Credentials never leave the machine** (keyring) and never enter the repo.
- **Event content** *necessarily* reaches whichever LLM is used — this is
  inherent to "let an LLM read my calendar," not something the tool can hide.
  Mitigations: the overlap skill prefers `get_free_busy` (dates + busy/free
  only); a `--fields` option can restrict returned fields. For institute/shared
  data, GWDG (German-hosted) may be the more appropriate *model* even if Claude
  is more capable — the tool is model-agnostic so the user chooses per task.
- **Server stays local.** No internet-exposed endpoint. Remote LLM = remote
  *API*, local *tool*.
- **Network egress** from the tool is only to the configured CalDAV hosts
  (Kerio needs institute network/VPN; iCloud is public).

## 12. Testing

- **Local Radicale** CalDAV server fixture for integration tests — zero real
  credentials, full create/read/update/delete/recurrence coverage.
- Unit tests for the iCal builder, recurrence/`--scope` logic, date parsing,
  registry/role resolution, audit log.
- A `--dry-run` golden-output test per write command.
- No test ever contacts Kerio/iCloud or needs a real password.

## 13. Repo layout

```
calendar-mcp-server/
├── DESIGN.md                 ← this file
├── README.md                 ← quick start (public)
├── pyproject.toml
├── calmcp/
│   ├── caldav_client.py      ← connect, discover, upsert, delete (from add_to_calendar.py)
│   ├── registry.py           ← calendars.yaml + roles
│   ├── auth.py               ← keyring + fallback prompt
│   ├── ical.py               ← event build/parse, recurrence
│   ├── audit.py
│   ├── cli.py                ← `calmcp` entry point (the true interface)
│   └── mcp_server.py         ← MCP adapter
├── skills/                   ← dates-to-events.md, overlap-check.md, bulk-edit.md
├── tests/                    ← pytest + Radicale fixture
├── calendars.example.yaml    ← committed template
└── calendars.yaml            ← LOCAL, git-ignored (real accounts)
```

## 14. Build phases

| Phase | Deliverable | Est. (part-time) |
|---|---|---|
| **0** | core + CLI: registry, auth/keyring, `list_calendars`, `query_events` (expanded). **Read-only, Kerio.** Radicale tests. | 2–3 d |
| **1** | add iCloud account; `get_free_busy`; `find_events`; `export_ics`; overlap-check skill. Still read-only. | 3–4 d |
| **2** | MCP adapter; `dates-to-events` + `bulk-edit` skills. | 2–3 d |
| **3** | writes: `create/update/move/delete` (dry-run, `--scope this|all`, role-confirm, audit log). | 3–5 d |
| **4** | optional: `thisAndFuture` series split; Google via API. | +1 wk |

Usable read-only multi-account tool + overlap report in ~1.5 weeks; writes
shortly after.

## 15. Open questions

- iCloud app-specific password: generate when Phase 1 starts.
- ~~Where to store the audit log + `calendars.yaml`~~ **Decided:** `calendars.yaml`
  is repo-local (git-ignored, `--registry`/`$CALMCP_REGISTRY` to relocate); the
  audit log goes to the XDG state dir (`~/.local/state/calmcp/audit.jsonl`,
  platform-appropriate, `$CALMCP_STATE_DIR` to override).
- ~~Whether the MCP adapter shells out to the CLI or imports the lib~~
  **Decided:** both the CLI and the MCP adapter call a shared `service` layer
  in-process (no shelling out).
- GWDG: confirm whether it can be driven as an MCP client or only via a local
  agent calling the CLI (affects which adapter the user relies on).

## 16. Implementation status

- **Phase 0–4 implemented** (CalDAV): registry, keyring auth, read commands
  (`list_calendars`, `query_events`, `find_events`, `get_free_busy`,
  `export_ics`), write commands (`create/update/move/delete_event`) with
  dry-run + role-gate + audit log, recurrence `--scope this|all|thisAndFuture`,
  the MCP adapter, and the three skills. Tested against a local Radicale server.
- **Deferred:** Google via its API (Phase 4 optional) — needs interactive OAuth
  and credentials that can't run in the offline test harness; out of scope for
  the CalDAV-first tool until there's a concrete need.
