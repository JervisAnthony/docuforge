import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ToolCard } from './ToolCard'

const tool = {
  id: 'pdf-merge',
  category: 'pdf',
  title: 'Merge PDF',
  description: 'Combine PDF documents.',
  endpoint: '/api/v1/pdf/merge',
  interfaceStatus: 'backend-ready',
} as const

describe('ToolCard', () => {
  it('uses an article and communicates that the interface is not operational', () => {
    render(<ToolCard tool={tool} />)
    const article = screen.getByRole('article')
    expect(article).toContainElement(screen.getByRole('heading', { name: 'Merge PDF' }))
    expect(article).toHaveTextContent('Combine PDF documents.')
    expect(article).toHaveTextContent('Backend ready · Interface coming next')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(article).not.toHaveTextContent('/api/v1/pdf/merge')
  })
})
