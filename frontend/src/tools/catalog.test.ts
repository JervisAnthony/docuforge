import { describe, expect, it } from 'vitest'
import { toolCatalog, toolsForCategory } from './catalog'

describe('tool catalog', () => {
  it('contains sixteen operational capabilities with unique IDs', () => {
    expect(toolCatalog).toHaveLength(16)
    expect(new Set(toolCatalog.map((tool) => tool.id)).size).toBe(16)
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
    expect(toolsForCategory('office').map((tool) => tool.title)).toEqual([
      'Word to PDF',
      'PowerPoint to PDF',
      'Excel to PDF',
    ])
    expect(toolsForCategory('ocr').map((tool) => tool.title)).toEqual([
      'Image to Text',
      'Scanned PDF to Text',
      'Searchable PDF',
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
      '/api/v1/office/docx-to-pdf',
      '/api/v1/office/pptx-to-pdf',
      '/api/v1/office/xlsx-to-pdf',
      '/api/v1/ocr/image-to-text',
      '/api/v1/ocr/pdf-to-text',
      '/api/v1/ocr/pdf-to-searchable-pdf',
    ])
    expect(toolCatalog.every((tool) => tool.interfaceStatus === 'operational')).toBe(true)
  })
})
