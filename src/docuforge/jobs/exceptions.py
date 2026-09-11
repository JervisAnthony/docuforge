"""Exceptions raised by the DocuForge job-processing foundation."""

from docuforge.core.exceptions import DocuForgeError


class JobError(DocuForgeError):
    """Base exception for expected job-processing errors."""


class InvalidJobDefinitionError(JobError):
    """Raised when a job value or lifecycle timestamp is invalid."""


class InvalidJobTransitionError(JobError):
    """Raised when a job cannot move to the requested state."""


class JobNotFoundError(JobError):
    """Raised when a job repository does not contain the requested job."""


class DuplicateJobError(JobError):
    """Raised when a job repository already contains the supplied job ID."""
