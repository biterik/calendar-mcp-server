# Skill: overlap-check
_Author: Erik Bitzek <e.bitzek@mpi-susmat.de> - PolyForm Noncommercial License 1.0.0_

Check one or more target dates for conflicts and surrounding context across all
of the user's calendars, so they can spot clashes and looming commitments before
committing to something new.

This skill is **read-only**. It works with either the `calmcp` CLI or the MCP
tools of the same name.

## When to use

The user gives you one or more dates (or a date range) and asks things like
"am I free?", "what's around the 14th?", "any conflicts that week?", or is about
to add an event and wants to sanity-check it first.

## Privacy

Prefer `get_free_busy` when the user only needs to know *whether* they are free —
it returns merged busy intervals with **no titles or locations**, minimising what
reaches the model. Only fall back to `query_events` when the user wants to see
*what* the conflicting items actually are.

## Procedure

For each target date `D`:

1. **Same-day + neighbours + the week after.** Query the window
   `[D-1 … D+7]` across all calendars. This deliberately captures:
   - the **day before** (`D-1`) — travel/prep spillover,
   - the **target day** (`D`),
   - the **day after** (`D+1`) — recovery/return,
   - the **week after** (`D+2 … D+7`) — looming conferences and deadlines.

   ```bash
   # Minimal data (free/busy only):
   calmcp get_free_busy --from <D-1> --to <D+7> --json
   # Or, if the user wants details:
   calmcp query_events --from <D-1> --to <D+7> --expand --json
   ```

2. **Classify** the results relative to `D`:
   - **Conflicts** — anything overlapping `D` itself (especially timed/busy
     events). Call these out first and clearly.
   - **Adjacent** — events on `D-1` and `D+1`.
   - **Looming** — events in `D+2 … D+7`, flagging anything that looks like a
     conference, travel, or a deadline (keywords, all-day multi-day blocks).

3. **Report** as a compact table per target date, e.g.:

   | When | Event | Calendar | Note |
   |------|-------|----------|------|
   | D 09:00–10:00 | Project Sync | work | **conflict** |
   | D-1 (all day) | Travel to Berlin | personal | adjacent |
   | D+3 | DFG deadline | work | looming |

   If using `get_free_busy`, report busy blocks instead of named events and say
   so ("titles hidden for privacy — ask if you want details").

4. **Conclude** with a one-line verdict per date: free / has conflicts / busy
   surroundings, and offer to look closer or to draft an event (see the
   `dates-to-events` skill).

## Notes

- Always pass `--expand` to `query_events` so recurring events show every
  occurrence in the window.
- Multiple target dates: run the window per date; if dates are close together,
  one wider query covering them all is fine — just classify each date locally.
- Times in `get_free_busy` are UTC ISO-8601; convert to the user's timezone
  (`defaults.timezone`) when presenting.
