import type {
  ApiErrorPayload,
  ApiHealth,
  ApiMetadata,
  BinaryResponse,
} from './types'

type ApiClientErrorKind = 'network' | 'http' | 'malformed-response'
type FetchImplementation = typeof fetch

export class ApiClientError extends Error {
  readonly kind: ApiClientErrorKind
  readonly status: number | null
  readonly code: string | null

  constructor(
    message: string,
    options: {
      kind: ApiClientErrorKind
      status?: number
      code?: string
      cause?: unknown
    },
  ) {
    super(message, { cause: options.cause })
    this.name = 'ApiClientError'
    this.kind = options.kind
    this.status = options.status ?? null
    this.code = options.code ?? null
  }
}

export interface ApiClient {
  getMetadata(): Promise<ApiMetadata>
  getHealth(): Promise<ApiHealth>
  postMultipartForBlob(path: string, formData: FormData): Promise<BinaryResponse>
}

export function createApiClient(
  baseUrl = '',
  fetchImplementation: FetchImplementation = fetch,
): ApiClient {
  const normalizedBaseUrl = normalizeBaseUrl(baseUrl)

  async function request(path: string, init?: RequestInit): Promise<Response> {
    try {
      return await fetchImplementation(joinApiUrl(normalizedBaseUrl, path), init)
    } catch (error: unknown) {
      throw new ApiClientError('The DocuForge API could not be reached.', {
        kind: 'network',
        cause: error,
      })
    }
  }

  async function requestJson<T>(
    path: string,
    validate: (value: unknown) => value is T,
  ): Promise<T> {
    const response = await request(path, { headers: { Accept: 'application/json' } })
    if (!response.ok) {
      throw await createHttpError(response)
    }

    const payload = await parseJson(response)
    if (!validate(payload)) {
      throw new ApiClientError('The API returned an unexpected response.', {
        kind: 'malformed-response',
        status: response.status,
      })
    }
    return payload
  }

  return {
    getMetadata: () => requestJson('/api/v1', isApiMetadata),
    getHealth: () => requestJson('/api/v1/health', isApiHealth),
    async postMultipartForBlob(path, formData) {
      const response = await request(path, {
        method: 'POST',
        body: formData,
        headers: { Accept: 'application/octet-stream' },
      })
      if (!response.ok) {
        throw await createHttpError(response)
      }
      return {
        blob: await response.blob(),
        contentType: response.headers.get('content-type'),
      }
    },
  }
}

export function joinApiUrl(baseUrl: string, path: string): string {
  const normalizedBaseUrl = normalizeBaseUrl(baseUrl)
  const normalizedPath = `/${path.trim().replace(/^\/+/, '')}`
  return `${normalizedBaseUrl}${normalizedPath}`
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, '')
}

async function createHttpError(response: Response): Promise<ApiClientError> {
  const payload = await parseJson(response)
  if (isApiErrorPayload(payload)) {
    return new ApiClientError(payload.message, {
      kind: 'http',
      status: response.status,
      code: payload.code,
    })
  }
  return new ApiClientError(`The API request failed (${response.status}).`, {
    kind: 'http',
    status: response.status,
  })
}

async function parseJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isApiMetadata(value: unknown): value is ApiMetadata {
  return (
    isRecord(value) &&
    typeof value.name === 'string' &&
    typeof value.version === 'string' &&
    value.status === 'available'
  )
}

function isApiHealth(value: unknown): value is ApiHealth {
  return (
    isRecord(value) &&
    value.status === 'ok' &&
    value.service === 'docuforge' &&
    typeof value.version === 'string'
  )
}

function isApiErrorPayload(value: unknown): value is ApiErrorPayload {
  return (
    isRecord(value) &&
    typeof value.code === 'string' &&
    typeof value.message === 'string'
  )
}

export const apiClient = createApiClient(import.meta.env.VITE_API_BASE_URL)
