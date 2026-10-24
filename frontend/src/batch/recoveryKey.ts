import type { BatchSessionHandle } from '../api/types'

// Canonical UUID plus an opaque URL-safe capability, bounded by the server limit.
const KEY_PATTERN = /^DFB1:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([A-Za-z0-9_-]{1,256})$/

export function encodeRecoveryKey(handle: BatchSessionHandle): string {
  return `DFB1:${handle.snapshot.id}:${handle.accessToken}`
}

export function decodeRecoveryKey(key: string): { batchId: string; accessToken: string } | null {
  if (key.length > 298 || Array.from(key).some((char) => char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127)) return null
  const match = KEY_PATTERN.exec(key)
  return match ? { batchId: match[1], accessToken: match[2] } : null
}
