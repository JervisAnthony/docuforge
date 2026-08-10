"""Public image converter API."""

from docuforge.converters.image.convert_path import convert_image_path
from docuforge.converters.image.exceptions import ImageProcessingError
from docuforge.converters.image.models import (
    ImageCompressPathRequest,
    ImageCompressPathResult,
    ImageConvertPathRequest,
    ImageConvertPathResult,
    ImageInput,
    ImageResizePathRequest,
    ImageResizePathResult,
    ImageToPdfPathRequest,
    ImageToPdfPathResult,
    ImageToPdfRequest,
)
from docuforge.converters.image.optimize_path import (
    compress_image_path,
    resize_image_path,
)
from docuforge.converters.image.paths_to_pdf import convert_images_to_pdf
from docuforge.converters.image.to_pdf import ImageToPdfConverter

__all__ = [
    "ImageCompressPathRequest",
    "ImageCompressPathResult",
    "ImageConvertPathRequest",
    "ImageConvertPathResult",
    "ImageInput",
    "ImageProcessingError",
    "ImageResizePathRequest",
    "ImageResizePathResult",
    "ImageToPdfConverter",
    "ImageToPdfPathRequest",
    "ImageToPdfPathResult",
    "ImageToPdfRequest",
    "compress_image_path",
    "convert_image_path",
    "convert_images_to_pdf",
    "resize_image_path",
]
