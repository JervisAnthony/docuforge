import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  downloadBlob,
  filenameFromContentDisposition,
  sanitizeDownloadFilename,
} from './download'

describe('download utilities', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:docuforge-result'),
      revokeObjectURL: vi.fn(),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses ordinary and quoted Content-Disposition filenames', () => {
    expect(
      filenameFromContentDisposition('attachment; filename=merged.pdf', 'fallback.pdf'),
    ).toBe('merged.pdf')
    expect(
      filenameFromContentDisposition('attachment; filename="split pages.zip"', 'fallback.zip'),
    ).toBe('split pages.zip')
  })

  it('sanitizes paths and rejects unsafe or blank filenames', () => {
    expect(sanitizeDownloadFilename('../private/report.pdf')).toBe('..privatereport.pdf')
    expect(sanitizeDownloadFilename('bad\u0000name.pdf')).toBeNull()
    expect(sanitizeDownloadFilename('  ')).toBeNull()
    expect(filenameFromContentDisposition('attachment; filename="../"', 'safe.pdf')).toBe(
      'safe.pdf',
    )
  })

  it('falls back when the header is absent or malformed', () => {
    expect(filenameFromContentDisposition(null, 'merged.pdf')).toBe('merged.pdf')
    expect(filenameFromContentDisposition('attachment', 'merged.pdf')).toBe('merged.pdf')
  })

  it('clicks a temporary anchor and always revokes the object URL', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    downloadBlob(new Blob(['pdf']), 'merged.pdf')
    expect(URL.createObjectURL).toHaveBeenCalledOnce()
    expect(click).toHaveBeenCalledOnce()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:docuforge-result')
    expect(document.querySelector('a[download]')).not.toBeInTheDocument()
  })
})
