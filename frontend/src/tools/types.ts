export type ToolCategory = 'pdf' | 'image'
export type PdfToolId =
  | 'pdf-merge'
  | 'pdf-split'
  | 'pdf-rotate'
  | 'pdf-remove-pages'
  | 'pdf-extract-pages'
  | 'pdf-to-images'
export type ImageToolId =
  | 'image-convert'
  | 'image-resize'
  | 'image-compress'
  | 'images-to-pdf'
export type ToolId = PdfToolId | ImageToolId

interface ToolMetadata {
  title: string
  description: string
  endpoint: string
}

export interface PdfToolDefinition extends ToolMetadata {
  id: PdfToolId
  category: 'pdf'
  interfaceStatus: 'operational'
}

export interface ImageToolDefinition extends ToolMetadata {
  id: ImageToolId
  category: 'image'
  interfaceStatus: 'backend-ready'
}

export type ToolDefinition = PdfToolDefinition | ImageToolDefinition
