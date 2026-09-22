"""Cryptographic capabilities for private anonymous batch sessions."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

BATCH_TOKEN_HEADER = "X-DocuForge-Batch-Token"
MAX_ACCESS_TOKEN_LENGTH = 256
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def generate_access_token() -> str:
    """Return a URL-safe capability containing 256 bits of randomness."""
    return secrets.token_urlsafe(32)


def hash_access_token(access_token: str) -> str:
    """Hash a validated plaintext capability for storage."""
    if not access_token_is_valid(access_token):
        raise ValueError("access token is invalid")
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()


def access_token_is_valid(access_token: object) -> bool:
    """Return whether a supplied capability has a safe, narrow shape."""
    return (
        isinstance(access_token, str)
        and bool(access_token.strip())
        and len(access_token) <= MAX_ACCESS_TOKEN_LENGTH
    )


def access_token_hash_is_valid(access_token_hash: object) -> bool:
    """Return whether a stored digest is canonical lowercase SHA-256 hex."""
    return isinstance(access_token_hash, str) and _HASH_PATTERN.fullmatch(access_token_hash) is not None


def verify_access_token(access_token: object, expected_hash: str) -> bool:
    """Verify a supplied capability using constant-time digest comparison."""
    if not access_token_is_valid(access_token) or not access_token_hash_is_valid(expected_hash):
        return False
    candidate_hash = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate_hash, expected_hash)
