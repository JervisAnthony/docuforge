import type { ToolDefinition } from './types'

export const toolCatalog = [
  {
    id: 'batch-image-convert',
    category: 'batch',
    title: 'Batch image convert',
    description: 'Convert multiple images while tracking each file independently.',
    endpoint: '/api/v1/batches/images/convert',
    interfaceStatus: 'operational',
  },
  {
    id: 'batch-image-resize',
    category: 'batch',
    title: 'Batch image resize',
    description: 'Resize multiple images with progress and per-file status.',
    endpoint: '/api/v1/batches/images/resize',
    interfaceStatus: 'operational',
  },
  {
    id: 'batch-image-compress',
    category: 'batch',
    title: 'Batch image compress',
    description: 'Compress multiple images and download successful results together.',
    endpoint: '/api/v1/batches/images/compress',
    interfaceStatus: 'operational',
  },
  {
    id: 'batch-office-to-pdf',
    category: 'batch',
    title: 'Batch Office to PDF',
    description: 'Convert mixed Word, PowerPoint, and Excel files to PDF as one tracked batch.',
    endpoint: '/api/v1/batches/office/to-pdf',
    interfaceStatus: 'operational',
  },
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
  {
    id: 'office-docx-to-pdf',
    category: 'office',
    title: 'Word to PDF',
    description: 'Convert a DOCX document into a PDF.',
    endpoint: '/api/v1/office/docx-to-pdf',
    interfaceStatus: 'operational',
  },
  {
    id: 'office-pptx-to-pdf',
    category: 'office',
    title: 'PowerPoint to PDF',
    description: 'Convert a PPTX presentation into a PDF.',
    endpoint: '/api/v1/office/pptx-to-pdf',
    interfaceStatus: 'operational',
  },
  {
    id: 'office-xlsx-to-pdf',
    category: 'office',
    title: 'Excel to PDF',
    description: 'Convert an XLSX workbook into a PDF.',
    endpoint: '/api/v1/office/xlsx-to-pdf',
    interfaceStatus: 'operational',
  },
  {
    id: 'ocr-image-to-text',
    category: 'ocr',
    title: 'Image to Text',
    description: 'Extract selectable text from a scanned image.',
    endpoint: '/api/v1/ocr/image-to-text',
    interfaceStatus: 'operational',
  },
  {
    id: 'ocr-pdf-to-text',
    category: 'ocr',
    title: 'Scanned PDF to Text',
    description: 'Extract text from every page of a scanned PDF.',
    endpoint: '/api/v1/ocr/pdf-to-text',
    interfaceStatus: 'operational',
  },
  {
    id: 'ocr-pdf-to-searchable-pdf',
    category: 'ocr',
    title: 'Searchable PDF',
    description: 'Turn a scanned PDF into a searchable PDF document.',
    endpoint: '/api/v1/ocr/pdf-to-searchable-pdf',
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
