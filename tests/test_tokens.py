# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""OAuth credential encryption at rest.

A refresh token is a long-lived key to a whole Drive, so the properties under
test are that plaintext never reaches the column or the logs, and that a wrong
or missing key fails loudly rather than returning a plausible-looking wrong
value or silently writing plaintext.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from go2.config import get_settings
from go2.security.tokens import (
    TokenDecryptError,
    TokenKeyError,
    decrypt_token,
    encrypt_token,
)
from go2.storage import repository as repo
from go2.storage.db import connect
from go2.tenancy import create_tenant, delete_tenant, resolve_tenant_id

if TYPE_CHECKING:
    from collections.abc import Iterator

# A realistic-looking Google refresh token, never a real one.
TOKEN = "1//09Ftpj-refresh-0AeanDsAbCdEf_GhIjKlMnOpQrStUvWxYz1234567890"


def _database_available() -> bool:
    try:
        with connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


@pytest.fixture
def _key(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A fresh Fernet key in the environment, isolated from the settings cache."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("GO2_FERNET_KEY", key)
    get_settings.cache_clear()
    yield key
    get_settings.cache_clear()


@pytest.mark.usefixtures("_key")
def test_a_token_round_trips() -> None:
    assert decrypt_token(encrypt_token(TOKEN)) == TOKEN


@pytest.mark.usefixtures("_key")
def test_the_stored_blob_is_not_the_plaintext() -> None:
    blob = encrypt_token(TOKEN)
    assert TOKEN.encode() not in blob
    assert TOKEN not in blob.decode("latin-1")


def test_a_missing_key_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GO2_FERNET_KEY", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(TokenKeyError, match="GO2_FERNET_KEY is not set"):
            encrypt_token(TOKEN)
        # An empty credential needs no key, so the upload path keeps working.
        assert encrypt_token("") == b""
        assert decrypt_token(b"") == ""
    finally:
        get_settings.cache_clear()


def test_a_wrong_key_does_not_silently_return_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GO2_FERNET_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    try:
        blob = encrypt_token(TOKEN)
    finally:
        get_settings.cache_clear()
    monkeypatch.setenv("GO2_FERNET_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    try:
        with pytest.raises(TokenDecryptError):
            decrypt_token(blob)
    finally:
        get_settings.cache_clear()


@pytest.mark.usefixtures("_key")
def test_tokens_are_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        blob = encrypt_token(TOKEN)
        assert decrypt_token(blob) == TOKEN
    assert TOKEN not in caplog.text
    assert blob.decode("latin-1") not in caplog.text


@pytest.mark.slow
class TestTokenAtRest:
    """The credential in the database, through ensure_connection and load_token."""

    @pytest.fixture
    def tenant(self, _key: str) -> Iterator[str]:
        if not _database_available():  # pragma: no cover - environment dependent
            pytest.skip("no database reachable")
        slug = f"t-{uuid.uuid4().hex[:10]}"
        create_tenant(slug)
        try:
            yield resolve_tenant_id(slug)
        finally:
            delete_tenant(slug)

    def test_the_column_holds_ciphertext_and_load_returns_the_plaintext(self, tenant: str) -> None:
        with connect() as conn:
            connection_id = repo.ensure_connection(
                conn, tenant_id=tenant, source="gdrive", account="me@example.com", token=TOKEN
            )
            raw = conn.execute(
                text("SELECT token_blob FROM connections WHERE id = :i AND tenant_id = :t"),
                {"i": connection_id, "t": tenant},
            ).scalar_one()
        # The column is ciphertext: the plaintext is not a substring of it.
        assert TOKEN.encode() not in bytes(raw)
        # A fresh connection stands in for a process restart.
        with connect() as conn:
            loaded = repo.load_token(conn, tenant_id=tenant, connection_id=connection_id)
        assert loaded == TOKEN

    def test_a_connection_without_a_token_reads_back_empty(self, tenant: str) -> None:
        with connect() as conn:
            connection_id = repo.ensure_connection(
                conn, tenant_id=tenant, source="upload", account="local"
            )
            loaded = repo.load_token(conn, tenant_id=tenant, connection_id=connection_id)
        assert loaded == ""

    def test_load_token_is_scoped_to_the_tenant(self, tenant: str) -> None:
        with connect() as conn:
            connection_id = repo.ensure_connection(
                conn, tenant_id=tenant, source="gdrive", account="me@example.com", token=TOKEN
            )
        other = str(uuid.uuid4())  # a different tenant cannot read the credential
        with connect() as conn, pytest.raises(KeyError):
            repo.load_token(conn, tenant_id=other, connection_id=connection_id)
