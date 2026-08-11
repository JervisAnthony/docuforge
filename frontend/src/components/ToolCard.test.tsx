import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ToolCard } from './ToolCard'

const pdfTool = {
  id: 'pdf-merge',
  category: 'pdf',
  title: 'Merge PDF',
  description: 'Combine PDF documents.',
  endpoint: '/api/v1/pdf/merge',
  interfaceStatus: 'operational',
} as const

const imageTool = {
  id: 'image-convert',
  category: 'image',
  title: 'Convert image',
  description: 'Convert image formats.',
  endpoint: '/api/v1/images/convert',
  interfaceStatus: 'backend-ready',
} as const

describe('ToolCard', () => {
  it('exposes a real action for an operational PDF tool', () => {
    render(<ToolCard tool={pdfTool} onOpen={() => undefined} />)
    const article = screen.getByRole('article')
    expect(article).toContainElement(screen.getByRole('heading', { name: 'Merge PDF' }))
    expect(article).toHaveTextContent('Combine PDF documents.')
    expect(article).toHaveTextContent('Ready')
    expect(screen.getByRole('button', { name: 'Open Merge PDF' })).toBeEnabled()
    expect(article).not.toHaveTextContent('/api/v1/pdf/merge')
  })

  it('keeps an image tool truthful and non-operational', () => {
    render(<ToolCard tool={imageTool} />)
    const article = screen.getByRole('article')
    expect(article).toHaveTextContent('Backend ready · Interface coming next')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(article).not.toHaveTextContent('/api/v1/images/convert')
  })
})
