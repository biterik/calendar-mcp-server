# Skill: bulk-edit
_Author: Erik Bitzek <e.bitzek@mpi-susmat.de> - PolyForm Noncommercial License 1.0.0_

Make the same change across many events safely: **find → show the list → edit
item by item**. Never issue a blind bulk write.

Works with either the `calmcp` CLI or the MCP tools of the same name.

## When to use

"Rename all my X meetings", "move every Y next week by an hour", "delete the
old Z series", "add a location to all the …". Anything that touches more than one
event.

## Core rule

The tool deliberately has **no blind bulk-write primitive**. A bulk change is
always: enumerate with `find_events`, present the enumerated list, then loop
`update_event` / `move_event` / `delete_event` over the *individual* results.
This keeps every write addressable, idempotent, and auditable.

## Procedure

1. **Enumerate** the targets:

   ```bash
   calmcp find_events --from <start> --to <end> --q "<text>" --json
   ```

   Results are recurrence-expanded: each row has `calendar_id`, `uid`, and (for
   recurring series) a `recurrence_id`.

2. **Show the list** to the user and confirm the set is correct (and the exact
   change) before touching anything. Note any rows on non-owned calendars.

3. **Decide scope per recurring series.** A recurring event is one resource with
   one `uid`. To edit it use `--scope`:
   - `all` — change the whole series (edit the master once; do **not** loop over
     its expanded occurrences).
   - `this` — change a single occurrence; pass its `--recurrence-id`.
   - `thisAndFuture` — split the series from that occurrence onward.

   Do not call `update_event` once per expanded occurrence of the same series —
   that is wrong (they share a uid). Collapse occurrences of one series to a
   single `--scope all` edit, or address specific ones with `--scope this`.

4. **Dry-run the loop first.** For each distinct target call the write *without*
   `--confirm` and show the `before`/`after`. Let the user eyeball the diff.

5. **Apply** on approval, item by item:

   ```bash
   calmcp update_event --calendar <id> --uid <uid> --set summary="New name" --confirm
   calmcp move_event   --calendar <id> --uid <uid> --start "<s>" --end "<e>" --confirm
   calmcp delete_event --calendar <id> --uid <uid> --scope all --confirm
   ```

   - Non-owned calendars (role != `owner`) warn and require `--confirm-foreign`.
   - Every real write is recorded in the audit log, so the user can review/undo.

6. **Summarise** results: how many changed, skipped, or failed (with reasons).

## Notes

- `--set` accepts `summary`, `location`, `description`, `status`, `reminder`
  (repeat `--set` for several fields). Times/calendar moves go through
  `move_event`, not `--set`.
- If a `thisAndFuture` split can't be done cleanly on the backend, the tool
  refuses and tells the user to do that one in the calendar app — relay that
  rather than forcing it.
- Keep batches reviewable: for large sets, page through in chunks and confirm
  each chunk.
