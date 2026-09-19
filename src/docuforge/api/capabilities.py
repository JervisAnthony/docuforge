"""Safe runtime capability probing for optional local conversion engines."""

from dataclasses import dataclass

from docuforge.api.ocr import OcrEngineFactory
from docuforge.api.office import OfficeEngineFactory
from docuforge.converters.ocr import OcrEngineUnavailableError
from docuforge.converters.office import OfficeEngineUnavailableError


@dataclass(frozen=True, slots=True)
class RuntimeCapability:
    """Public availability state without runtime or filesystem details."""

    available: bool


@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    """Availability of the production engines exposed by the API."""

    office_to_pdf: RuntimeCapability
    ocr: RuntimeCapability


def probe_runtime_capabilities(
    *,
    office_engine_factory: OfficeEngineFactory,
    ocr_engine_factory: OcrEngineFactory,
) -> RuntimeCapabilities:
    """Construct configured engines and verify their public contracts."""
    return RuntimeCapabilities(
        office_to_pdf=RuntimeCapability(
            available=_probe_office(office_engine_factory)
        ),
        ocr=RuntimeCapability(available=_probe_ocr(ocr_engine_factory)),
    )


def _probe_office(factory: OfficeEngineFactory) -> bool:
    try:
        engine = factory()
    except OfficeEngineUnavailableError:
        return False
    return callable(getattr(engine, "convert_to_pdf", None))


def _probe_ocr(factory: OcrEngineFactory) -> bool:
    try:
        engine = factory()
    except OcrEngineUnavailableError:
        return False
    return callable(getattr(engine, "recognize", None))
