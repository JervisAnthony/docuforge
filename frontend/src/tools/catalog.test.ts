import { describe, expect, it } from 'vitest'
import { toolCatalog, toolsForCategory } from './catalog'

describe('tool catalog', () => {
  it('contains the ten backend capabilities with unique IDs', () => {
    expect(toolCatalog).toHaveLength(10)
    expect(new Set(toolCatalog.map((tool) => tool.id)).size).toBe(10)
    expect(toolsForCategory('pdf').map((tool) => tool.title)).toEqual([
      'Merge PDF',
      'Split PDF',
      'Rotate PDF',
      'Remove pages',
      'Extract pages',
      'PDF to images',
    ])
    expect(toolsForCategory('image').map((tool) => tool.title)).toEqual([
      'Convert image',
      'Resize image',
      'Compress image',
      'Images to PDF',
    ])
  })

  it('matches the existing API endpoint contract', () => {
    expect(toolCatalog.map((tool) => tool.endpoint)).toEqual([
      '/api/v1/pdf/merge',
      '/api/v1/pdf/split',
      '/api/v1/pdf/rotate',
      '/api/v1/pdf/remove-pages',
      '/api/v1/pdf/extract-pages',
      '/api/v1/pdf/to-images',
      '/api/v1/images/convert',
      '/api/v1/images/resize',
      '/api/v1/images/compress',
      '/api/v1/images/to-pdf',
    ])
    expect(toolsForCategory('pdf').every((tool) => tool.interfaceStatus === 'operational')).toBe(
      true,
    )
    expect(
      toolsForCategory('image').every((tool) => tool.interfaceStatus === 'backend-ready'),
    ).toBe(true)
  })
})
