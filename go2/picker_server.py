# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""A local, loopback-only page for picking Google Drive files and folders.

`drive.file` grants this app nothing until the user picks it, and only
Google's own Picker widget can do that picking -- Drive enforces the grant at
the token level, so no server-side file browser we could build ourselves
would ever see more than the widget already lets through. This module serves
that widget: one page that loads it with the tenant's own access token, and
one endpoint where the widget's callback hands the selection back.

Built on the same Starlette + uvicorn stack `go2/mcp_server.py` already uses
for ``go2 serve --http`` -- no new framework dependency.

Deliberately storage-agnostic: this module never touches the database. It
returns the raw picked items to its caller, which persists them -- the same
separation `go2/connectors/gdrive.py` keeps from `go2/storage/repository.py`.
"""

from __future__ import annotations

import json
import logging
import secrets
import webbrowser
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

_FOLDER_MIME = "application/vnd.google-apps.folder"

# Rendered with .format(...): braces in the JS itself are doubled ({{ }}).
_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Pick Drive files for go2</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 32rem; margin: 3rem auto;">
<h1>Pick files or a folder</h1>
<p id="status">Loading Google's picker&hellip;</p>
<script src="https://apis.google.com/js/api.js"></script>
<script>
const ACCESS_TOKEN = {access_token!r};
const DEVELOPER_KEY = {developer_key!r};
const CSRF_TOKEN = {csrf_token!r};

function onApiLoad() {{
  gapi.load('picker', {{callback: onPickerApiLoad}});
}}

function onPickerApiLoad() {{
  const view = new google.picker.DocsView(google.picker.ViewId.DOCS)
    .setIncludeFolders(true)
    .setSelectFolderEnabled(true);
  const picker = new google.picker.PickerBuilder()
    .addView(view)
    .setOAuthToken(ACCESS_TOKEN)
    .setDeveloperKey(DEVELOPER_KEY)
    .setCallback(pickerCallback)
    .build();
  document.getElementById('status').textContent = '';
  picker.setVisible(true);
}}

function pickerCallback(data) {{
  if (data.action === google.picker.Action.PICKED) {{
    const items = data.docs.map(function(d) {{
      return {{id: d.id, name: d.name, mimeType: d.mimeType}};
    }});
    fetch('/selection', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{csrf_token: CSRF_TOKEN, items: items}}),
    }}).then(function() {{
      document.body.innerHTML = '<h1>Saved &mdash; you can close this tab.</h1>';
    }}).catch(function() {{
      document.getElementById('status').textContent =
        'Something went wrong saving the selection; go back to the terminal.';
    }});
  }} else if (data.action === google.picker.Action.CANCEL) {{
    document.body.innerHTML = '<h1>Cancelled &mdash; you can close this tab.</h1>';
  }}
}}

window.onload = onApiLoad;
</script>
</body></html>
"""


@dataclass
class PickerSession:
    """Holds the outcome of one picker run, and how to stop the server."""

    result: list[tuple[str, str, str]] | None = field(default=None, init=False)
    _stop: Callable[[], None] | None = field(default=None, init=False, repr=False)

    def bind_stop(self, stop: Callable[[], None]) -> None:
        """Wire up how to end the server once a selection arrives."""
        self._stop = stop

    def submit(self, items: list[tuple[str, str, str]]) -> None:
        """Record the picked items and end the session."""
        self.result = items
        if self._stop is not None:
            self._stop()


def _kind_of(mime: str) -> str:
    return "folder" if mime == _FOLDER_MIME else "file"


def build_picker_app(
    *, access_token: str, developer_key: str, csrf_token: str, session: PickerSession
) -> ASGIApp:
    """The ASGI application ``go2 picker`` runs.

    Separate from running it so a test can drive it in-process, the same
    shape as ``go2.mcp_server.build_http_app``.

    Args:
        access_token: A live Drive API bearer token, freshly refreshed --
            never the long-lived refresh token. Rendered into the page for
            the Picker widget's own ``setOAuthToken``; this is how Google's
            documented Picker integration works, not a leak specific to this
            server.
        developer_key: The Picker API key from Cloud Console.
        csrf_token: A per-session secret. Gates both the page itself and the
            selection endpoint, so another local process or browser tab
            cannot read the access token or forge a selection.
        session: Where the picked items land, and how the server is told
            to stop once they do.
    """

    async def index(request: Request) -> Response:
        if not secrets.compare_digest(request.query_params.get("t", ""), csrf_token):
            return Response(status_code=404)
        page = _PAGE.format(
            access_token=access_token, developer_key=developer_key, csrf_token=csrf_token
        )
        return HTMLResponse(page)

    async def selection(request: Request) -> Response:
        try:
            body: dict[str, Any] = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        if not secrets.compare_digest(str(body.get("csrf_token", "")), csrf_token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        items = body.get("items")
        if not isinstance(items, list) or not items:
            return JSONResponse({"error": "no items"}, status_code=400)
        try:
            parsed = [
                (
                    str(item["id"]),
                    _kind_of(str(item.get("mimeType", ""))),
                    str(item.get("name", "")),
                )
                for item in items
            ]
        except (KeyError, TypeError):
            return JSONResponse({"error": "malformed item"}, status_code=400)
        session.submit(parsed)
        return JSONResponse({"saved": len(parsed)})

    return Starlette(routes=[Route("/", index), Route("/selection", selection, methods=["POST"])])


def run_picker(
    *, port: int, access_token: str, developer_key: str, open_browser: bool = True
) -> list[tuple[str, str, str]] | None:
    """Serve the picker page until one selection is submitted.

    Args:
        port: Loopback port to bind. There is no ``--host`` to widen this --
            a one-person file picker has no legitimate reason to be reachable
            beyond this machine.
        access_token: A live, already-refreshed Drive API bearer token.
        developer_key: The Picker API key from Cloud Console.
        open_browser: Open the page automatically. Off in tests.

    Returns:
        ``(external_id, kind, title)`` tuples for what was picked, or
        ``None`` if the server was interrupted before a selection arrived.
    """
    import uvicorn  # noqa: PLC0415 -- a server dependency; keep it out of the CLI import path.

    csrf_token = secrets.token_urlsafe(24)
    session = PickerSession()
    app = build_picker_app(
        access_token=access_token,
        developer_key=developer_key,
        csrf_token=csrf_token,
        session=session,
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    session.bind_stop(lambda: setattr(server, "should_exit", True))

    url = f"http://127.0.0.1:{port}/?t={csrf_token}"
    if open_browser:
        webbrowser.open(url)
    logger.info("picker listening at %s", url)
    server.run()
    return session.result
