"""Stable batch and item UUID identity contracts."""

import json
from uuid import UUID

import pytest

from docuforge.batch import BatchId, BatchItemId, InvalidBatchDefinitionError


@pytest.mark.parametrize("id_type", [BatchId, BatchItemId])
def test_identifiers_accept_uuid_and_normalize_uppercase(id_type: type[BatchId | BatchItemId]) -> None:
    value = UUID("A1B2C3D4-E5F6-47A8-9B0C-0D1E2F3A4B5C")
    assert id_type(value) == str(value)
    assert id_type(str(value).upper()) == str(value)
    assert isinstance(id_type(str(value)), str)
    assert json.loads(json.dumps({"id": id_type(value)})) == {"id": str(value)}


@pytest.mark.parametrize("id_type", [BatchId, BatchItemId])
def test_new_identifiers_are_distinct_valid_uuids(id_type: type[BatchId | BatchItemId]) -> None:
    first, second = id_type.new(), id_type.new()
    assert first != second
    assert str(UUID(first)) == first
    assert str(UUID(second)) == second


@pytest.mark.parametrize("id_type", [BatchId, BatchItemId])
@pytest.mark.parametrize("value", ["", "not-a-uuid", None, object(), 7])
def test_invalid_identifiers_raise_batch_definition_error(
    id_type: type[BatchId | BatchItemId], value: object,
) -> None:
    with pytest.raises(InvalidBatchDefinitionError, match="Invalid"):
        id_type(value)  # type: ignore[arg-type]
