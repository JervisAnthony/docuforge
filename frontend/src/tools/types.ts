export type ToolCategory = 'pdf' | 'image' | 'office'
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
export type OfficeToolId = 'office-docx-to-pdf' | 'office-pptx-to-pdf' | 'office-xlsx-to-pdf'
export type ToolId = PdfToolId | ImageToolId | OfficeToolId
export type ToolInterfaceStatus = 'operational' | 'backend-ready'

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
  interfaceStatus: 'operational'
}

export interface OfficeToolDefinition extends ToolMetadata {
  id: OfficeToolId
  category: 'office'
  interfaceStatus: 'operational'
}

export type BackendReadyToolDefinition = ToolMetadata &
  (
    | { id: PdfToolId; category: 'pdf'; interfaceStatus: 'backend-ready' }
    | { id: ImageToolId; category: 'image'; interfaceStatus: 'backend-ready' }
    | { id: OfficeToolId; category: 'office'; interfaceStatus: 'backend-ready' }
  )

export type ToolDefinition =
  | PdfToolDefinition
  | ImageToolDefinition
  | OfficeToolDefinition
  | BackendReadyToolDefinition
