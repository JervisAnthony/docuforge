import type { MultipartRequestClient } from '../workflows/useSubmission'

export type PdfRequestClient = MultipartRequestClient

export interface PdfFormProps {
  client?: PdfRequestClient
}
