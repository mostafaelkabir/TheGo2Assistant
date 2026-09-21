---
id: T-013
title: Google Picker with the drive.file scope
status: in-progress
phase: 1-drive
priority: P2
blocked_by: [T-012]
github_issue: 13
owner: Claude (Sonnet 5)
branch: drive/picker
pr:
created: 2026-09-03
updated: 2026-09-20
closed:
---

## Problem

`drive.file` only grants what the user explicitly picks, so without a picker
there is nothing to sync. This is the piece that turns the tool into
something a client can connect themselves.

## Definition

`go2 picker`: starts a local, loopback-only web page (Starlette + uvicorn,
the same stack `go2 serve --http` already uses -- no new framework
dependency) and opens it in the browser. The page loads Google's actual
Picker JS widget, authorised with the tenant's already-stored, freshly
refreshed access token (`ensure_fresh`, from T-011). A Google Picker
**API key** -- a second, separate Cloud Console credential from the OAuth
client -- is required by the widget itself; `GO2_GOOGLE_PICKER_API_KEY` is
a new setting for it. **`drive.file` cannot be worked around with a
custom file browser**: the scope only ever grants access to items chosen
through Google's own Picker (or "Open with", or app-created files) --
Drive's API enforces this at the token level, so nothing server-side can
list a user's wider Drive regardless of UI.

On selection, the page `POST`s the picked item ids and kind (file or
folder) to `/selection` on the same local server, which persists them --
not expanded to files yet. A migration adds `drive_selections
(id, tenant_id, connection_id, external_id, kind, title, removed_at,
created_at)`, `UNIQUE (connection_id, external_id)`, following
`001_init.sql`'s tenant_id-on-every-table convention.

`go2 sync` changes: when a connection has any active (`removed_at IS
NULL`) selection, list results are filtered to selected files plus the
current contents of selected folders, expanded **at sync time** (a new
`GoogleDriveConnector.list_folder_children` method, `q="'<id>' in
parents"`, walked recursively) rather than snapshotted at pick time --
so a file added to an already-picked folder later is synced without
re-picking. A connection with zero active selections syncs nothing and
says so, the same friendly shape as "no connection, run `go2 connect
google` first".

`go2 picker list` / `go2 picker remove <external_id>` manage existing
selections from the terminal; removing one stops future syncs of it
without touching documents already indexed (no cascade delete on
`connections` -&gt; `documents`, only on the selection row itself).

Does not deliver: a UI to browse or remove selections in the picker page
itself (CLI only, for now); OneDrive's own picker (the table shape is
provider-neutral -- `source`-agnostic via `connection_id` -- but nothing
implements a second one here); re-authenticating the picker page itself
(it reuses the connection's existing OAuth credential, so `go2 connect
google` must already have been run).

## Success metrics

- A client can pick a folder in a browser and its contents sync, with
  nothing outside the selection visible to `list_documents`.
- The selection survives a restart of the serving process.
- A file added to an already-picked folder in Drive appears on the next
  `go2 sync` without picking again.

## Test cases

- `test_only_picked_files_are_listed`
- `test_a_picked_folder_includes_its_children`
- `test_the_selection_survives_a_restart`
- `test_removing_a_selection_stops_future_syncs` -- without deleting
  already-indexed content absent an explicit purge
- `test_a_file_added_to_a_picked_folder_later_is_synced` -- proves
  sync-time expansion, not a pick-time snapshot
- `test_a_connection_with_no_selection_syncs_nothing_and_says_so`

## Design notes

Reuses `go2/mcp_server.py`'s established shape for a local server:
`build_picker_app(...) -&gt; ASGIApp` (mirrors `build_http_app`), tested with
`starlette.testclient.TestClient(app, base_url="http://127.0.0.1:&lt;port&gt;")`
per `tests/test_mcp_server.py`'s own fixture pattern. Loopback-only, no
`--host` option to widen it -- there is no legitimate reason to expose a
one-person file picker beyond this machine, so the question T-016/serve's
bearer-token model exists to answer does not need re-answering here.

The Picker JS widget itself (rendered and driven entirely in the user's
own browser) is not something a Python test suite can drive; coverage
here is the server side only -- serving the page, and the `/selection`
endpoint's persistence and validation. The live, real-Picker path is a
manual verification step, the same limit T-011's real consent screen hit.

## Work log

- 2026-09-03 — Opened as GitHub issue #13.
- 2026-09-16 — Mirrored into the local backlog.

- 2026-09-20 — T-012 closed; unblocked. Rewrote the Definition with a
  concrete design (Starlette local server reusing `go2/mcp_server.py`'s
  shape, sync-time folder expansion rather than a pick-time snapshot, a
  new `drive_selections` table) before claiming, per the ticket workflow.
  Claimed by Claude (Sonnet 5) on `drive/picker` -- the owner wants to
  interact with real Drive files as a non-technical company-owner
  persona; confirmed `drive.file` cannot be worked around without this.

## Outcome
