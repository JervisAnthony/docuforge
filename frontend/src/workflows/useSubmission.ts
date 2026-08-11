import { useRef, useState } from 'react'
import { ApiClientError, apiClient } from '../api/client'
import type { ApiClient } from '../api/client'
import { downloadBlob, filenameFromContentDisposition } from '../utils/download'

export type MultipartRequestClient = Pick<ApiClient, 'postMultipartForBlob'>

export type WorkflowFeedback =
  | { status: 'idle' }
  | { status: 'ready' }
  | { status: 'submitting' }
  | { status: 'success'; filename: string }
  | { status: 'error'; message: string }

export function useSubmission(
  client: MultipartRequestClient = apiClient,
  unexpectedError = 'The file could not be processed. Please try again.',
) {
  const [feedback, setFeedback] = useState<WorkflowFeedback>({ status: 'idle' })
  const submittingRef = useRef(false)

  function reset(ready: boolean) {
    if (!submittingRef.current) {
      setFeedback({ status: ready ? 'ready' : 'idle' })
    }
  }

  async function submit(endpoint: string, formData: FormData, fallbackFilename: string) {
    if (submittingRef.current) {
      return
    }
    submittingRef.current = true
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
      setFeedback({ status: 'error', message: userFacingError(error, unexpectedError) })
    } finally {
      submittingRef.current = false
    }
  }

  return { feedback, reset, submit }
}

function userFacingError(error: unknown, fallback: string): string {
  if (error instanceof ApiClientError) {
    return error.message
  }
  return fallback
}
