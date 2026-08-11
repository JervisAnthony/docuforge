import { useEffect, useState } from 'react'
import { apiClient } from '../api/client'
import type { ApiHealth } from '../api/types'

type ConnectionState =
  | { status: 'checking' }
  | { status: 'connected'; version: string }
  | { status: 'unavailable' }

interface ApiStatusProps {
  checkHealth?: () => Promise<ApiHealth>
}

const checkApiHealth = () => apiClient.getHealth()

export function ApiStatus({
  checkHealth = checkApiHealth,
}: ApiStatusProps) {
  const [connection, setConnection] = useState<ConnectionState>({
    status: 'checking',
  })

  useEffect(() => {
    let active = true

    void checkHealth().then(
      (health) => {
        if (active) {
          setConnection({ status: 'connected', version: health.version })
        }
      },
      () => {
        if (active) {
          setConnection({ status: 'unavailable' })
        }
      },
    )

    return () => {
      active = false
    }
  }, [checkHealth])

  const label =
    connection.status === 'connected'
      ? `API connected · v${connection.version}`
      : connection.status === 'unavailable'
        ? 'API unavailable'
        : 'Checking API'

  return (
    <div
      className={`api-status api-status--${connection.status}`}
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <span className="api-status__dot" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}
