export type ToolCategory = 'pdf' | 'image'
export type ToolInterfaceStatus = 'backend-ready'

export interface ToolDefinition {
  id: string
  category: ToolCategory
  title: string
  description: string
  endpoint: string
  interfaceStatus: ToolInterfaceStatus
}
