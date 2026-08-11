import { describe, expect, it } from 'vitest'
import {
  IMAGE_FORMAT_SUFFIX,
  IMAGE_TO_PDF_ACCEPT,
  RASTER_IMAGE_ACCEPT,
  imageFormatFromFilename,
  isImageToPdfFile,
  isRasterImageFile,
} from './formats'

describe('image format contract', () => {
  it.each([
    ['photo.jpg', 'jpeg'],
    ['photo.JPEG', 'jpeg'],
    ['graphic.png', 'png'],
    ['graphic.WEBP', 'webp'],
    ['scan.bmp', 'bmp'],
    ['scan.tif', 'tiff'],
    ['scan.TIFF', 'tiff'],
    ['unknown.gif', null],
    ['no-extension', null],
  ])('normalizes %s to %s', (filename, expected) => {
    expect(imageFormatFromFilename(filename)).toBe(expected)
  })

  it('centralizes canonical fallback suffixes', () => {
    expect(IMAGE_FORMAT_SUFFIX).toEqual({
      jpeg: 'jpg',
      png: 'png',
      webp: 'webp',
      bmp: 'bmp',
      tiff: 'tiff',
    })
  })

  it('matches the broader raster route and narrower image-to-PDF route', () => {
    expect(RASTER_IMAGE_ACCEPT).toBe('.jpg,.jpeg,.png,.webp,.bmp,.tif,.tiff')
    expect(IMAGE_TO_PDF_ACCEPT).toBe('.jpg,.jpeg,.png,.bmp,.tif,.tiff')
    expect(isRasterImageFile(new File(['x'], 'photo.webp'))).toBe(true)
    expect(isImageToPdfFile(new File(['x'], 'photo.webp'))).toBe(false)
    for (const name of ['a.jpg', 'a.jpeg', 'a.png', 'a.bmp', 'a.tif', 'a.tiff']) {
      expect(isImageToPdfFile(new File(['x'], name))).toBe(true)
    }
  })
})
