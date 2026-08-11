export type ImageFormat = 'jpeg' | 'png' | 'webp' | 'bmp' | 'tiff'

export interface ImageFormatDefinition {
  value: ImageFormat
  label: string
  suffix: 'jpg' | 'png' | 'webp' | 'bmp' | 'tiff'
}

export const IMAGE_FORMATS = [
  { value: 'jpeg', label: 'JPEG', suffix: 'jpg' },
  { value: 'png', label: 'PNG', suffix: 'png' },
  { value: 'webp', label: 'WebP', suffix: 'webp' },
  { value: 'bmp', label: 'BMP', suffix: 'bmp' },
  { value: 'tiff', label: 'TIFF', suffix: 'tiff' },
] as const satisfies readonly ImageFormatDefinition[]

export const IMAGE_FORMAT_SUFFIX: Readonly<Record<ImageFormat, ImageFormatDefinition['suffix']>> = {
  jpeg: 'jpg',
  png: 'png',
  webp: 'webp',
  bmp: 'bmp',
  tiff: 'tiff',
}

export const RASTER_IMAGE_ACCEPT = '.jpg,.jpeg,.png,.webp,.bmp,.tif,.tiff'
export const IMAGE_TO_PDF_ACCEPT = '.jpg,.jpeg,.png,.bmp,.tif,.tiff'

const formatByExtension: Readonly<Record<string, ImageFormat>> = {
  jpg: 'jpeg',
  jpeg: 'jpeg',
  png: 'png',
  webp: 'webp',
  bmp: 'bmp',
  tif: 'tiff',
  tiff: 'tiff',
}

const imageToPdfExtensions = new Set(['jpg', 'jpeg', 'png', 'bmp', 'tif', 'tiff'])

export function imageFormatFromFilename(filename: string): ImageFormat | null {
  const extension = filename.match(/\.([^.]+)$/)?.[1].toLowerCase()
  return extension ? (formatByExtension[extension] ?? null) : null
}

export function isRasterImageFile(file: File): boolean {
  return imageFormatFromFilename(file.name) !== null
}

export function isImageToPdfFile(file: File): boolean {
  const extension = file.name.match(/\.([^.]+)$/)?.[1].toLowerCase()
  return Boolean(extension && imageToPdfExtensions.has(extension))
}

export function isImageFormat(value: string): value is ImageFormat {
  return IMAGE_FORMATS.some((format) => format.value === value)
}
