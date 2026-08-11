export type PageListResult =
  | { ok: true; pages: number[] }
  | { ok: false; message: string }

export function parsePageList(value: string): PageListResult {
  if (!value.trim()) {
    return { ok: false, message: 'Enter at least one page number.' }
  }

  const segments = value.split(',')
  if (segments.some((segment) => !segment.trim())) {
    return { ok: false, message: 'Separate page numbers with single commas.' }
  }

  const pages: number[] = []
  const seen = new Set<number>()
  for (const segment of segments) {
    const token = segment.trim()
    if (!/^[1-9]\d*$/.test(token)) {
      return {
        ok: false,
        message: 'Use positive whole page numbers separated by commas; ranges are not supported.',
      }
    }
    const page = Number(token)
    if (!Number.isSafeInteger(page)) {
      return { ok: false, message: 'Page numbers are too large.' }
    }
    if (seen.has(page)) {
      return { ok: false, message: `Page ${page} is listed more than once.` }
    }
    seen.add(page)
    pages.push(page)
  }
  return { ok: true, pages }
}
