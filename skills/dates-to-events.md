# Skill: dates-to-events
_Author: Erik Bitzek <e.bitzek@mpi-susmat.de> - PolyForm Noncommercial License 1.0.0_

Turn a pasted list of dates (or an attached PDF / text) into calendar events:
propose them, fill gaps with the user, show a review table, and on confirmation
write them one by one. Optionally emit an `.ics` for sharing.

Works with either the `calmcp` CLI or the MCP tools of the same name. **You** do
the parsing and judgement; the tool only provides primitives.

## When to use

The user pastes dates/an itinerary/a conference programme/a PDF and asks to "add
these to my calendar", "block these", "put these trips in", etc.

## Procedure

1. **Extract** the candidate events from the input. For each, gather:
   - `summary` (title),
   - `start` / `end` — a date (all-day) or `YYYY-MM-DD HH:MM` (timed),
   - `all_day` (true if no times given),
   - `location`, `description` (optional),
   - `reminder` (optional: `0`, `30m`, `2h`, `1d`).

2. **Suggest a calendar** per event using the registry. Run `list_calendars`
   to see the configured ids/roles, and use `defaults.write_calendar` as the
   fallback. Pick by content (e.g. work vs family) but never silently write to a
   calendar the user did not expect.

3. **Ask once** for everything missing or ambiguous — batch all questions into a
   single message (missing times, which calendar, reminders) rather than
   drip-feeding.

4. **Check for clashes (recommended).** Before showing the table, run the
   `overlap-check` skill (or a quick `get_free_busy`) over the proposed dates and
   note any conflicts in the table so the user decides with full context.

5. **Show a review table** and wait for explicit confirmation:

   | # | Summary | When | Calendar | Reminder | Note |
   |---|---------|------|----------|----------|------|
   | 1 | DFG meeting | 2026-09-01 (all day) | work | 1d | clash? none |

6. **Dry-run first.** For each row call `create_event` *without* `--confirm` and
   show the `before`/`after` contract. This catches mistakes before any write.

7. **On "yes", write each row** with `--confirm`:

   ```bash
   calmcp create_event --calendar <id> --summary "<title>" \
       --start "<start>" --end "<end>" [--all-day] \
       [--location "<loc>"] [--reminder <spec>] --confirm
   ```

   - If a calendar's role is not `owner`, the result carries a `not owner`
     warning and the write is refused unless you also pass `--confirm-foreign`.
     Surface this to the user and only proceed with explicit approval.
   - Reuse a stable `--uid` if you may re-run (idempotent upsert — no duplicates).

8. **Report** what was written (and any skipped/failed rows with the reason).

## Sharing an .ics

If the user wants to send the events to someone, export the same range:

```bash
calmcp export_ics --from <first> --to <last> --out events.ics
```

## Notes

- All-day events: `end` is the **last day** the user means; the tool handles the
  exclusive DTEND internally.
- Timezone comes from `defaults.timezone`; only override with explicit times.
- Never write without showing the review table and getting a clear "yes".
- Privacy: event content reaches whichever model you are. For institute/shared
  data prefer the German-hosted model if the user has set that up.
