export function filenameFromContentDisposition(
  contentDisposition: string | null,
  fallback: string,
): string {
  if (!contentDisposition) {
    return fallback
  }

  const match = /(?:^|;)\s*filename\s*=\s*(?:"([^"]*)"|([^;]*))/i.exec(
    contentDisposition,
  )
  const candidate = (match?.[1] ?? match?.[2] ?? '').trim()
  return sanitizeDownloadFilename(candidate) ?? fallback
}

export function sanitizeDownloadFilename(value: string): string | null {
  const hasControlCharacter = Array.from(value).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0
    return codePoint <= 0x1f || codePoint === 0x7f
  })
  if (!value || hasControlCharacter) {
    return null
  }
  const sanitized = value.replace(/[\\/]/g, '').trim()
  if (!sanitized || sanitized === '.' || sanitized === '..') {
    return null
  }
  return sanitized
}

export function downloadBlob(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  try {
    anchor.href = objectUrl
    anchor.download = filename
    anchor.hidden = true
    document.body.append(anchor)
    anchor.click()
  } finally {
    anchor.remove()
    URL.revokeObjectURL(objectUrl)
  }
}
