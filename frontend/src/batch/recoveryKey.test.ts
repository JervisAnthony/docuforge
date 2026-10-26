import { describe, expect, it } from 'vitest'
import { decodeRecoveryKey, encodeRecoveryKey } from './recoveryKey'
import type { BatchSessionHandle } from '../api/types'

const id = '12345678-1234-4234-8234-123456789abc'
const token = 'a_b-C0123'
const key = `DFB1:${id}:${token}`

describe('recovery keys', () => {
  it('round trips original identity and opaque capability', () => {
    expect(encodeRecoveryKey({ snapshot: { id }, accessToken: token } as BatchSessionHandle)).toBe(key)
    expect(decodeRecoveryKey(key)).toEqual({ batchId: id, accessToken: token })
  })
  it.each(['', 'DFB2:' + id + ':' + token, 'DFB1:batch-1:token', `DFB1:${id}:`, key + ':extra', key + '\n', key + '\r', key + '\t', key + '\x00', key + ' ', `DFB1:${id}:has/slash`, `DFB1:${id}:has=padding`, `DFB1:${id}:${'a'.repeat(257)}`])('rejects malformed input %#', (input) => {
    expect(decodeRecoveryKey(input)).toBeNull()
  })
  it('accepts the server capability length limit', () => {
    expect(decodeRecoveryKey(`DFB1:${id}:${'a'.repeat(256)}`)?.accessToken).toHaveLength(256)
  })
})
