import { describe, expect, it } from 'vitest'
import { parsePageList } from './pageList'

describe('parsePageList', () => {
  it.each([
    ['2', [2]],
    ['2,4,7', [2, 4, 7]],
    ['2, 4, 7', [2, 4, 7]],
    ['4,2,5', [4, 2, 5]],
  ])('accepts %s and preserves order', (value, expected) => {
    expect(parsePageList(value)).toEqual({ ok: true, pages: expected })
  })

  it.each(['', '0', '-1', '1.5', 'abc', '2,,4', '2,2', '2-4'])(
    'rejects %j',
    (value) => {
      expect(parsePageList(value).ok).toBe(false)
    },
  )
})
