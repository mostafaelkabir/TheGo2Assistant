# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Encryption of OAuth credentials at rest.

A refresh token is a long-lived key to somebody's whole Drive; it must never
sit in Postgres as plaintext. One module knows the format -- the same
single-place principle the egress guard follows -- so there is one place to
audit and one place that can fail loudly.

The key is a Fernet key (AES-128-CBC with an HMAC), read from ``GO2_FERNET_KEY``
and never from code. It is needed only when there is a real token to protect:
an empty credential encrypts to empty bytes and decrypts back to the empty
string, so the upload path, which has no token, never needs a key. The moment a
real token is encrypted or decrypted without a valid key the call raises, with
an actionable message and nothing written -- never a silent plaintext write or
a garbage decrypt.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from go2.config import get_settings

_GENERATE_HINT = (
    "Generate one with "
    '`python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"` and set it in '
    "~/.config/go2/.env; it encrypts OAuth tokens at rest."
)


class TokenKeyError(RuntimeError):
    """``GO2_FERNET_KEY`` is missing or is not a valid Fernet key."""


class TokenDecryptError(RuntimeError):
    """A stored token could not be decrypted with the configured key.

    Its own type so a wrong or rotated key surfaces as an error the caller can
    act on, never as a plausible-looking but wrong plaintext.
    """


def _cipher() -> Fernet:
    key = get_settings().fernet_key.get_secret_value()
    if not key:
        msg = f"GO2_FERNET_KEY is not set. {_GENERATE_HINT}"
        raise TokenKeyError(msg)
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        msg = f"GO2_FERNET_KEY is not a valid Fernet key (44-char urlsafe base64). {_GENERATE_HINT}"
        raise TokenKeyError(msg) from exc


def encrypt_token(plaintext: str) -> bytes:
    """Encrypt an OAuth credential for storage.

    An empty credential stays empty and needs no key, so a connection without a
    token (the upload path) never requires ``GO2_FERNET_KEY``.

    Raises:
        TokenKeyError: a real token was given but the key is missing or invalid.
            Nothing is returned, so no plaintext is written.
    """
    if plaintext == "":
        return b""
    return _cipher().encrypt(plaintext.encode())


def decrypt_token(blob: bytes) -> str:
    """Return the plaintext credential for a stored blob.

    Empty bytes decrypt to the empty string without a key.

    Raises:
        TokenKeyError: the key is missing or invalid.
        TokenDecryptError: the blob is not decryptable with the configured key
            (a wrong or rotated key), rather than silently returning garbage.
    """
    if not blob:
        return ""
    try:
        return _cipher().decrypt(blob).decode()
    except InvalidToken as exc:
        msg = "a stored token could not be decrypted with GO2_FERNET_KEY (wrong or rotated key)."
        raise TokenDecryptError(msg) from exc
