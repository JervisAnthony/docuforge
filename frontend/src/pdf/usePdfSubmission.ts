import { useSubmission } from '../workflows/useSubmission'
import type { PdfRequestClient } from './types'

export function usePdfSubmission(client?: PdfRequestClient) {
  return useSubmission(client, 'The PDF could not be processed. Please try again.')
}
