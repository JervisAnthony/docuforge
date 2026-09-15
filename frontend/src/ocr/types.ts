export interface OcrTextResult {
  text: string
  blob: Blob
  filename: string
}

export type OcrTextFeedback =
  | { status: 'idle' }
  | { status: 'ready' }
  | { status: 'submitting' }
  | { status: 'success' }
  | { status: 'error'; message: string }
