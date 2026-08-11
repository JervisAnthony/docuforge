import type { ApiHealth } from '../api/types'
import { ApiStatus } from './ApiStatus'

interface AppHeaderProps {
  checkHealth?: () => Promise<ApiHealth>
}

export function AppHeader({ checkHealth }: AppHeaderProps) {
  return (
    <header className="app-header">
      <div className="app-header__inner">
        <div className="brand" aria-label="DocuForge home">
          <span className="brand__mark" aria-hidden="true">
            D
          </span>
          <span>
            <span className="brand__name">DocuForge</span>
            <span className="brand__tagline">Focused tools for everyday files</span>
          </span>
        </div>
        <ApiStatus checkHealth={checkHealth} />
      </div>
    </header>
  )
}
