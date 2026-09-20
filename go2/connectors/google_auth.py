# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Authorizing go2 against a user's Google Drive account.

Scope is **`drive.file`**, not `drive.readonly`, and this is not a config knob
-- see `docs/roadmap.md`, "Phase 1 -- Google Drive, end to end". A personal
Gmail account cannot use the OAuth *Internal* user type (that needs a
Workspace organisation); External plus Testing revokes refresh tokens every
7 days, and leaving Testing for Production triggers a CASA security
assessment for the restricted `drive.readonly` scope. `drive.file` is
non-sensitive: Production without an audit, no weekly expiry, `changes.list`
still works. The cost, which T-013's picker exists to pay, is that the user
must pick files or folders explicitly rather than granting blanket read
access.

Because `drive.file` carries no identity scope, the authorized account's
email is not on the credentials or an ID token -- it comes from `about.get`
against the Drive the credentials were just granted for.

`OAuthCredentials` narrows `google.oauth2.credentials.Credentials` to the
slice this module depends on, the same way `go2.connectors.gdrive.DriveService`
narrows the discovery-built Drive client: tests drive a hand-rolled fake
against the real interface instead of mocking google-auth internals.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, WSGITimeoutError
from googleapiclient.discovery import build
from oauthlib.oauth2.rfc6749.errors import OAuth2Error

from go2.connectors.gdrive import SOURCE

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["SOURCE"]  # re-exported so callers need one import, not two.

# Deliberately one scope. test_the_requested_scope_is_drive_file guards
# against silently widening it back to something that needs a CASA audit.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class ClientSecretsNotFoundError(FileNotFoundError):
    """No OAuth client secret at the configured path."""

    def __init__(self, path: Path) -> None:
        """Name the path and how to obtain one."""
        super().__init__(
            f"no Google OAuth client secret at {path}. Create an OAuth client ID "
            "(type: Desktop app) at https://console.cloud.google.com/apis/credentials, "
            "download it, and save it at that path -- or point GO2_GOOGLE_CLIENT_SECRETS "
            "elsewhere."
        )


class AuthorizationFailedError(RuntimeError):
    """The installed-app flow did not produce credentials.

    Covers what oauthlib and the local callback server raise for real: consent
    denied, the OAuth exchange rejected, or the loopback callback timing out
    waiting for the browser. Wrapped so the CLI prints one clean line instead
    of a third-party traceback -- the fix is the same in every case, try
    again.
    """


class RevokedCredentialError(RuntimeError):
    """The stored refresh token no longer works.

    The account owner revoked access, the token expired from disuse, or the
    OAuth client was deleted -- from here they look the same, and the fix is
    the same: reauthorize.
    """

    def __init__(self, account: str) -> None:
        """Name the account and the fix."""
        super().__init__(
            f"Google refused to refresh go2's access to {account}. "
            "Reauthorize with `go2 connect google`."
        )


@runtime_checkable
class OAuthCredentials(Protocol):
    """The slice of `google.oauth2.credentials.Credentials` this module uses."""

    @property
    def expired(self) -> bool:
        """Whether the access token needs refreshing."""
        ...

    def refresh(self, request: Any) -> None:  # noqa: ANN401 -- google-auth's own signature.
        """Exchange the refresh token for a new access token."""
        ...

    def to_json(self) -> str:
        """Serialize the credential for storage."""
        ...


@runtime_checkable
class AboutCapableService(Protocol):
    """The slice of the Drive discovery client `account_email` needs."""

    def about(self) -> Any:  # noqa: ANN401 -- discovery-built resource has no static type.
        """Return the `about` resource."""
        ...


def run_installed_app_flow(client_secrets: Path) -> Credentials:
    """Run the installed-app OAuth flow, opening a browser for consent.

    Args:
        client_secrets: Path to the downloaded OAuth client secret JSON.

    Returns:
        Fresh credentials scoped to `SCOPES`.

    Raises:
        ClientSecretsNotFoundError: nothing at `client_secrets`.
        AuthorizationFailedError: consent was denied, the exchange was
            rejected, or the local callback timed out.
    """
    if not client_secrets.exists():
        raise ClientSecretsNotFoundError(client_secrets)
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), scopes=SCOPES)
    try:
        # The installed-app flow always yields user credentials, never the
        # workload-identity-federation kind the library's return type also allows.
        return cast("Credentials", flow.run_local_server(port=0))
    except (OAuth2Error, WSGITimeoutError) as exc:
        msg = f"Google authorization did not complete: {exc}. Run `go2 connect google` again."
        raise AuthorizationFailedError(msg) from exc


def build_drive_service(credentials: Credentials) -> Any:  # noqa: ANN401 -- discovery has no static type.
    """Build the Drive client these credentials authorize."""
    return build("drive", "v3", credentials=credentials)


def account_email(service: AboutCapableService) -> str:
    """Return the Drive account a built service is authorized for."""
    about = service.about().get(fields="user").execute()
    return str(about["user"]["emailAddress"])


def credentials_to_token(credentials: OAuthCredentials) -> str:
    """Serialize credentials to the string stored, encrypted, in `token_blob`."""
    return credentials.to_json()


def credentials_from_token(token: str) -> Credentials:
    """Reconstruct credentials from a stored token."""
    return Credentials.from_authorized_user_info(json.loads(token), scopes=SCOPES)


def ensure_fresh(credentials: OAuthCredentials, *, account: str) -> OAuthCredentials:
    """Refresh an expired access token in place, without prompting the user.

    A refresh token is long-lived and does not itself expire from use, so
    this is safe to call before every request rather than only after a 401 --
    `credentials.refresh` is a no-op cost when the access token is still
    valid, guarded here by the `expired` check.

    Args:
        credentials: Credentials to freshen, mutated in place by `refresh`.
        account: The authorized account, for an actionable error only.

    Returns:
        The same credentials, with a valid access token.

    Raises:
        RevokedCredentialError: the refresh token no longer works.
    """
    if not credentials.expired:
        return credentials
    try:
        credentials.refresh(GoogleAuthRequest())
    except RefreshError as exc:
        raise RevokedCredentialError(account) from exc
    return credentials
