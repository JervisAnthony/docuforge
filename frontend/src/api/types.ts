export interface ApiMetadata {
  name: string
  version: string
  status: 'available'
}

export interface ApiHealth {
  status: 'ok'
  service: 'docuforge'
  version: string
}

export interface ApiErrorPayload {
  code: string
  message: string
}

export interface BinaryResponse {
  blob: Blob
  contentType: string | null
  contentDisposition: string | null
}

export type BatchItemStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
export type BatchStatus = 'pending' | 'running' | 'completed' | 'failed' | 'partial' | 'cancelled'
export type BatchPhase = 'queued' | 'processing' | 'cancelling' | 'packaging' | 'ready' | 'error'

export interface BatchFailure {
  code: string
  message: string
}

export interface BatchItemSnapshot {
  id: string
  position: number
  descriptor: string
  status: BatchItemStatus
  result_descriptor: string | null
  failure: BatchFailure | null
}

export interface BatchSummary {
  total: number
  pending: number
  running: number
  completed: number
  failed: number
  cancelled: number
  processed: number
  remaining: number
}

export interface BatchSnapshot {
  id: string
  operation: string
  attempt: number
  phase: BatchPhase
  status: BatchStatus
  progress_percent: number
  cancellation_requested: boolean
  summary: BatchSummary
  items: BatchItemSnapshot[]
  session_error: BatchFailure | null
  can_cancel: boolean
  can_recover: boolean
  can_download: boolean
}

export interface BatchSessionHandle {
  snapshot: BatchSnapshot
  accessToken: string
}
