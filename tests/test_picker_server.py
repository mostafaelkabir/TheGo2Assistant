# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The picker's local server: serving the page, and the /selection endpoint.

The Picker JS widget itself runs in a real browser and talks to Google
directly -- no Python test suite can drive it. What's covered here is the
server side only: the page and the selection endpoint are both gated behind
the session token, and a submitted selection is classified and handed to the
caller correctly. The live, real-Picker path is a manual verification step,
the same limit T-011's real consent screen hit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from go2.picker_server import PickerSession, build_picker_app

if TYPE_CHECKING:
    from collections.abc import Iterator

TOKEN = "a-test-csrf-token"


@pytest.fixture
def picker() -> Iterator[tuple[TestClient, PickerSession]]:
    session = PickerSession()
    app = build_picker_app(
        access_token="an-access-token",
        developer_key="a-dev-key",
        csrf_token=TOKEN,
        session=session,
    )
    with TestClient(app) as client:
        yield client, session


class TestPage:
    def test_the_page_is_refused_without_the_session_token(
        self, picker: tuple[TestClient, PickerSession]
    ) -> None:
        client, _ = picker
        assert client.get("/").status_code == 404
        assert client.get("/?t=wrong-token").status_code == 404

    def test_the_page_with_the_right_token_loads_the_picker(
        self, picker: tuple[TestClient, PickerSession]
    ) -> None:
        client, _ = picker
        response = client.get(f"/?t={TOKEN}")
        assert response.status_code == 200
        assert "an-access-token" in response.text
        assert "a-dev-key" in response.text
        assert TOKEN in response.text
        assert "google.picker" in response.text


class TestSelection:
    def test_a_valid_selection_is_recorded_and_classified(
        self, picker: tuple[TestClient, PickerSession]
    ) -> None:
        client, session = picker
        response = client.post(
            "/selection",
            json={
                "csrf_token": TOKEN,
                "items": [
                    {"id": "f-1", "name": "Contract.pdf", "mimeType": "application/pdf"},
                    {
                        "id": "d-1",
                        "name": "Client Files",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                ],
            },
        )
        assert response.status_code == 200
        assert session.result == [
            ("f-1", "file", "Contract.pdf"),
            ("d-1", "folder", "Client Files"),
        ]

    def test_a_valid_selection_stops_the_server(
        self, picker: tuple[TestClient, PickerSession]
    ) -> None:
        client, session = picker
        stopped = []
        session.bind_stop(lambda: stopped.append(True))

        client.post(
            "/selection",
            json={"csrf_token": TOKEN, "items": [{"id": "f-1", "name": "A", "mimeType": "x"}]},
        )

        assert stopped == [True]

    def test_the_wrong_token_is_rejected_and_nothing_is_recorded(
        self, picker: tuple[TestClient, PickerSession]
    ) -> None:
        client, session = picker
        response = client.post(
            "/selection",
            json={
                "csrf_token": "not-the-token",
                "items": [{"id": "f-1", "name": "A", "mimeType": "x"}],
            },
        )
        assert response.status_code == 401
        assert session.result is None

    def test_an_empty_selection_is_rejected(self, picker: tuple[TestClient, PickerSession]) -> None:
        client, session = picker
        response = client.post("/selection", json={"csrf_token": TOKEN, "items": []})
        assert response.status_code == 400
        assert session.result is None

    def test_malformed_json_is_rejected(self, picker: tuple[TestClient, PickerSession]) -> None:
        client, session = picker
        response = client.post(
            "/selection", content=b"not json", headers={"content-type": "application/json"}
        )
        assert response.status_code == 400
        assert session.result is None

    def test_an_item_missing_its_id_is_rejected(
        self, picker: tuple[TestClient, PickerSession]
    ) -> None:
        client, session = picker
        response = client.post(
            "/selection",
            json={"csrf_token": TOKEN, "items": [{"name": "A", "mimeType": "x"}]},
        )
        assert response.status_code == 400
        assert session.result is None
