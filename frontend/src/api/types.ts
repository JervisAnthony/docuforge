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
}
