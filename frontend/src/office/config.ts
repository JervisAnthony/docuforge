import type { OfficeToolId } from '../tools/types'

export const officeConfig: Record<OfficeToolId, { extension: string; label: string }> = {
  'office-docx-to-pdf': { extension: '.docx', label: 'Word document' },
  'office-pptx-to-pdf': { extension: '.pptx', label: 'PowerPoint presentation' },
  'office-xlsx-to-pdf': { extension: '.xlsx', label: 'Excel workbook' },
}
