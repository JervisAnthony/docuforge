import type { OcrToolId } from '../tools/types'

export const imageExtensions = ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff'] as const
export const pdfExtensions = ['.pdf'] as const

export const ocrInputConfig: Record<
  OcrToolId,
  { extensions: readonly string[]; accept: string; label: string; help: string }
> = {
  'ocr-image-to-text': {
    extensions: imageExtensions,
    accept: imageExtensions.join(','),
    label: 'Image',
    help: 'Choose one supported raster image.',
  },
  'ocr-pdf-to-text': {
    extensions: pdfExtensions,
    accept: '.pdf',
    label: 'Scanned PDF',
    help: 'Choose one PDF document.',
  },
  'ocr-pdf-to-searchable-pdf': {
    extensions: pdfExtensions,
    accept: '.pdf',
    label: 'Scanned PDF',
    help: 'Choose one PDF document.',
  },
}

export function hasAllowedOcrExtension(filename: string, extensions: readonly string[]): boolean {
  const normalized = filename.toLowerCase()
  return extensions.some((extension) => normalized.endsWith(extension))
}

export function ocrFallbackFilename(filename: string, suffix: string): string {
  const basename = filename.replace(/\\/g, '/').split('/').pop() ?? ''
  const stem = basename.replace(/\.[^.]*$/, '') || 'document'
  return `${stem}${suffix}`
}
