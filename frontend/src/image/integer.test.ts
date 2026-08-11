import { describe, expect, it } from 'vitest'
import { parseKilobytesToBytes, parsePositiveInteger } from './integer'

describe('image integer parsing', () => {
  it.each([
    ['1', 1],
    ['200', 200],
    ['', null],
    ['0', null],
    ['-1', null],
    ['1.5', null],
    ['01', 1],
  ])('parses positive whole number %s', (value, expected) => {
    expect(parsePositiveInteger(value)).toBe(expected)
  })

  it('converts displayed KB to safe bytes', () => {
    expect(parseKilobytesToBytes('200')).toBe(204800)
    expect(parseKilobytesToBytes(String(Math.floor(Number.MAX_SAFE_INTEGER / 1024) + 1))).toBeNull()
  })
})
