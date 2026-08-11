import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ApiStatus } from './ApiStatus'

const health = { status: 'ok', service: 'docuforge', version: '0.1.0' } as const

describe('ApiStatus', () => {
  it('announces the checking state without blocking', () => {
    render(<ApiStatus checkHealth={() => new Promise(() => undefined)} />)
    expect(screen.getByRole('status')).toHaveTextContent('Checking API')
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite')
  })

  it('announces a connected API and its version', async () => {
    render(<ApiStatus checkHealth={() => Promise.resolve(health)} />)
    expect(await screen.findByText('API connected · v0.1.0')).toBeVisible()
  })

  it('announces an unavailable API after a rejected request', async () => {
    render(<ApiStatus checkHealth={() => Promise.reject(new Error('offline'))} />)
    expect(await screen.findByText('API unavailable')).toBeVisible()
  })
})
