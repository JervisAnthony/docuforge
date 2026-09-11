"""Tests for the job-processing exception contract."""

import pytest

from docuforge.core import DocuForgeError
from docuforge.jobs import (
    DuplicateJobError,
    InvalidJobDefinitionError,
    InvalidJobTransitionError,
    JobError,
    JobNotFoundError,
)


@pytest.mark.parametrize(
    "exception_type",
    [
        InvalidJobDefinitionError,
        InvalidJobTransitionError,
        JobNotFoundError,
        DuplicateJobError,
    ],
)
def test_job_exceptions_share_the_project_error_contract(
    exception_type: type[JobError],
) -> None:
    assert issubclass(exception_type, JobError)
    assert issubclass(exception_type, DocuForgeError)
