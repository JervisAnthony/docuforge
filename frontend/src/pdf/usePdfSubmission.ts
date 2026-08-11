import { useState } from 'react'
import { ApiClientError, apiClient } from '../api/client'
import { downloadBlob, filenameFromContentDisposition } from '../utils/download'
import type { PdfRequestClient } from './types'

export type WorkflowFeedback =
  | { status: 'idle' }
  | { status: 'ready' }
  | { status: 'submitting' }
  | { status: 'success'; filename: string }
  | { status: 'error'; message: string }

export function usePdfSubmission(client: PdfRequestClient = apiClient) {
  const [feedback, setFeedback] = useState<WorkflowFeedback>({ status: 'idle' })

  function reset(ready: boolean) {
    setFeedback({ status: ready ? 'ready' : 'idle' })
  }

  async function submit(endpoint: string, formData: FormData, fallbackFilename: string) {
    if (feedback.status === 'submitting') {
      return
    }
    setFeedback({ status: 'submitting' })
    try {
      const response = await client.postMultipartForBlob(endpoint, formData)
      const filename = filenameFromContentDisposition(
        response.contentDisposition,
        fallbackFilename,
      )
      downloadBlob(response.blob, filename)
      setFeedback({ status: 'success', filename })
    } catch (error: unknown) {
      setFeedback({ status: 'error', message: userFacingError(error) })
    }
  }

  return { feedback, reset, submit }
}

function userFacingError(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.message
  }
  return 'The PDF could not be processed. Please try again.'
}
