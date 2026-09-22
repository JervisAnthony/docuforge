"""Private batch capability helper coverage."""

from unittest.mock import patch

import pytest

from docuforge.api.batch_access import (
    MAX_ACCESS_TOKEN_LENGTH,
    access_token_hash_is_valid,
    access_token_is_valid,
    generate_access_token,
    hash_access_token,
    verify_access_token,
)


def test_generated_tokens_are_strong_url_safe_capabilities() -> None:
    first = generate_access_token()
    second = generate_access_token()

    assert first != second
    assert len(first) == 43
    assert access_token_is_valid(first)
    assert all(character.isalnum() or character in "-_" for character in first)


@pytest.mark.parametrize("candidate", [None, b"token", "", "   ", "x" * 257])
def test_token_shape_rejects_missing_blank_nonstring_and_oversized_values(
    candidate: object,
) -> None:
    assert not access_token_is_valid(candidate)


def test_hashing_is_canonical_and_verification_is_constant_time() -> None:
    token = "private-capability"
    digest = hash_access_token(token)

    assert len(digest) == 64
    assert digest == digest.lower()
    assert access_token_hash_is_valid(digest)
    with patch("docuforge.api.batch_access.hmac.compare_digest", return_value=True) as compare:
        assert verify_access_token(token, digest)
    compare.assert_called_once_with(hash_access_token(token), digest)


@pytest.mark.parametrize("digest", [None, "", "A" * 64, "0" * 63, "g" * 64])
def test_persisted_hash_validation_is_strict(digest: object) -> None:
    assert not access_token_hash_is_valid(digest)


def test_oversized_token_is_rejected_before_hashing() -> None:
    with pytest.raises(ValueError):
        hash_access_token("x" * (MAX_ACCESS_TOKEN_LENGTH + 1))
