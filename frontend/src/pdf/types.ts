import type { ApiClient } from '../api/client'

export type PdfRequestClient = Pick<ApiClient, 'postMultipartForBlob'>

export interface PdfFormProps {
  client?: PdfRequestClient
}
