import type { ToolDefinition } from './types'

export const toolCatalog = [
  {
    id: 'pdf-merge',
    category: 'pdf',
    title: 'Merge PDF',
    description: 'Combine multiple PDF documents in the order you choose.',
    endpoint: '/api/v1/pdf/merge',
    interfaceStatus: 'operational',
  },
  {
    id: 'pdf-split',
    category: 'pdf',
    title: 'Split PDF',
    description: 'Separate every page into its own downloadable PDF.',
    endpoint: '/api/v1/pdf/split',
    interfaceStatus: 'operational',
  },
  {
    id: 'pdf-rotate',
    category: 'pdf',
    title: 'Rotate PDF',
    description: 'Turn selected pages while preserving document order.',
    endpoint: '/api/v1/pdf/rotate',
    interfaceStatus: 'operational',
  },
  {
    id: 'pdf-remove-pages',
    category: 'pdf',
    title: 'Remove pages',
    description: 'Create a cleaner PDF without pages you no longer need.',
    endpoint: '/api/v1/pdf/remove-pages',
    interfaceStatus: 'operational',
  },
  {
    id: 'pdf-extract-pages',
    category: 'pdf',
    title: 'Extract pages',
    description: 'Build a new PDF from selected pages in your preferred order.',
    endpoint: '/api/v1/pdf/extract-pages',
    interfaceStatus: 'operational',
  },
  {
    id: 'pdf-to-images',
    category: 'pdf',
    title: 'PDF to images',
    description: 'Render document pages as high-quality image files.',
    endpoint: '/api/v1/pdf/to-images',
    interfaceStatus: 'operational',
  },
  {
    id: 'image-convert',
    category: 'image',
    title: 'Convert image',
    description: 'Change an image to JPEG, PNG, WebP, BMP, or TIFF.',
    endpoint: '/api/v1/images/convert',
    interfaceStatus: 'operational',
  },
  {
    id: 'image-resize',
    category: 'image',
    title: 'Resize image',
    description: 'Fit an image within new dimensions without distorting it.',
    endpoint: '/api/v1/images/resize',
    interfaceStatus: 'operational',
  },
  {
    id: 'image-compress',
    category: 'image',
    title: 'Compress image',
    description: 'Reduce file size using a quality or maximum file size target.',
    endpoint: '/api/v1/images/compress',
    interfaceStatus: 'operational',
  },
  {
    id: 'images-to-pdf',
    category: 'image',
    title: 'Images to PDF',
    description: 'Arrange multiple images as pages in one PDF document.',
    endpoint: '/api/v1/images/to-pdf',
    interfaceStatus: 'operational',
  },
] as const satisfies readonly ToolDefinition[]

export function toolsForCategory(category: ToolDefinition['category']) {
  return toolCatalog.filter((tool) => tool.category === category)
}

export function toolById(id: ToolDefinition['id']): ToolDefinition {
  const tool = toolCatalog.find((candidate) => candidate.id === id)
  if (!tool) {
    throw new Error(`Unknown tool: ${id}`)
  }
  return tool
}
