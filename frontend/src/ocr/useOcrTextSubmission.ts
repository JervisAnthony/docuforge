import { useRef, useState } from 'react'
import { ApiClientError, apiClient } from '../api/client'
import { filenameFromContentDisposition } from '../utils/download'
import type { MultipartRequestClient } from '../workflows/useSubmission'
import type { OcrTextFeedback, OcrTextResult } from './types'

const unexpectedError = 'The document could not be processed with OCR. Please try again.'

export function useOcrTextSubmission(client: MultipartRequestClient = apiClient) {
  const [feedback, setFeedback] = useState<OcrTextFeedback>({ status: 'idle' })
  const [result, setResult] = useState<OcrTextResult | null>(null)
  const submittingRef = useRef(false)

  function reset(ready: boolean) {
    if (submittingRef.current) return
    setResult(null)
    setFeedback({ status: ready ? 'ready' : 'idle' })
  }

  async function submit(endpoint: string, formData: FormData, fallbackFilename: string) {
    if (submittingRef.current) return
    submittingRef.current = true
    setResult(null)
    setFeedback({ status: 'submitting' })
    try {
      const response = await client.postMultipartForBlob(endpoint, formData)
      const text = await response.blob.text()
      setResult({
        text,
        blob: response.blob,
        filename: filenameFromContentDisposition(response.contentDisposition, fallbackFilename),
      })
      setFeedback({ status: 'success' })
    } catch (error: unknown) {
      setFeedback({
        status: 'error',
        message: error instanceof ApiClientError ? error.message : unexpectedError,
      })
    } finally {
      submittingRef.current = false
    }
  }

  return { feedback, result, reset, submit }
}
