# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The Google OAuth flow's own logic: scope, refresh, and revocation.

These run against hand-rolled fakes, not the real InstalledAppFlow or a real
Drive -- the properties under test are that a refresh never prompts the user
and that a revoked refresh token fails with a message naming the fix, not
whether Google's servers behave as documented.
"""

from __future__ import annotations

from typing import Any

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from go2.connectors.google_auth import (
    SCOPES,
    RevokedCredentialError,
    account_email,
    credentials_from_token,
    credentials_to_token,
    ensure_fresh,
)


class _FakeCredentials:
    """Stands in for google.oauth2.credentials.Credentials."""

    def __init__(self, *, expired: bool, refresh_token: str | None = "a-refresh-token") -> None:
        self.expired = expired
        self.refresh_token = refresh_token
        self.refresh_calls = 0
        self._fail_with: Exception | None = None

    def fail_refresh_with(self, exc: Exception) -> None:
        self._fail_with = exc

    def refresh(self, request: Any) -> None:
        assert request is not None
        self.refresh_calls += 1
        if self._fail_with is not None:
            raise self._fail_with
        self.expired = False

    def to_json(self) -> str:
        return "{}"


def test_the_requested_scope_is_drive_file() -> None:
    # Not drive.readonly: that scope needs the OAuth Internal user type (a
    # Workspace-only feature) or a CASA security assessment. A widened scope
    # here is a silent policy change, so it is pinned exactly.
    assert SCOPES == ["https://www.googleapis.com/auth/drive.file"]


def test_a_valid_token_is_not_refreshed() -> None:
    creds = _FakeCredentials(expired=False)
    ensure_fresh(creds, account="me@example.com")
    assert creds.refresh_calls == 0


def test_an_expired_access_token_is_refreshed() -> None:
    creds = _FakeCredentials(expired=True)
    result = ensure_fresh(creds, account="me@example.com")
    assert result is creds
    assert creds.refresh_calls == 1
    assert not creds.expired


def test_a_revoked_refresh_token_reports_actionably() -> None:
    creds = _FakeCredentials(expired=True)
    creds.fail_refresh_with(RefreshError("invalid_grant"))
    with pytest.raises(RevokedCredentialError, match="go2 connect google") as excinfo:
        ensure_fresh(creds, account="me@example.com")
    assert "me@example.com" in str(excinfo.value)


class _Call:
    """Mirrors googleapiclient's chained-call-then-execute shape."""

    def __init__(self, result: Any) -> None:
        self.result = result
        self.kwargs: dict[str, Any] = {}

    def __call__(self, **kwargs: Any) -> _Call:
        self.kwargs = kwargs
        return self

    def execute(self) -> Any:
        return self.result


class _About:
    def __init__(self, email: str) -> None:
        self.get = _Call({"user": {"emailAddress": email}})


class _DriveService:
    def __init__(self, email: str) -> None:
        self._about = _About(email)

    def about(self) -> _About:
        return self._about


def test_account_email_reads_the_authorized_drive_users_address() -> None:
    service = _DriveService("me@example.com")
    assert account_email(service) == "me@example.com"
    assert service._about.get.kwargs == {"fields": "user"}  # noqa: SLF001 -- inspecting our own fake.


def test_a_credential_round_trips_through_its_stored_token() -> None:
    original = Credentials(
        token="an-access-token",
        refresh_token="a-refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="a-client-id",
        client_secret="a-client-secret",
        scopes=SCOPES,
    )
    restored = credentials_from_token(credentials_to_token(original))
    assert restored.refresh_token == "a-refresh-token"
    assert restored.token == "an-access-token"
    assert restored.scopes == SCOPES
