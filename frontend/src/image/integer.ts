export function parsePositiveInteger(value: string): number | null {
  if (!/^\d+$/.test(value)) {
    return null
  }
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}

export function parseKilobytesToBytes(value: string): number | null {
  const kilobytes = parsePositiveInteger(value)
  if (kilobytes === null || kilobytes > Math.floor(Number.MAX_SAFE_INTEGER / 1024)) {
    return null
  }
  return kilobytes * 1024
}
