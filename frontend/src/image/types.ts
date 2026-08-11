import type { MultipartRequestClient } from '../workflows/useSubmission'

export type ImageRequestClient = MultipartRequestClient

export interface ImageFormProps {
  client?: ImageRequestClient
}

export type CompressionMode = 'quality' | 'max-size'
