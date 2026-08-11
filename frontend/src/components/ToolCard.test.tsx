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
  interfaceStatus: 'operational',
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

  it('exposes a real action for an operational image tool', () => {
    render(<ToolCard tool={imageTool} onOpen={() => undefined} />)
    const article = screen.getByRole('article')
    expect(article).toHaveTextContent('Ready')
    expect(screen.getByRole('button', { name: 'Open Convert image' })).toBeEnabled()
    expect(article).not.toHaveTextContent('/api/v1/images/convert')
  })
})
