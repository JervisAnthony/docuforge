import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

const pendingHealth = () => new Promise<never>(() => undefined)

describe('DocuForge application shell', () => {
  it('renders branding, semantic tool sections, and every tool exactly once', () => {
    render(<App checkHealth={pendingHealth} />)

    expect(screen.getByLabelText('DocuForge home')).toHaveTextContent('DocuForge')
    expect(
      screen.getByRole('heading', { level: 1, name: 'Choose the right tool for your file' }),
    ).toBeVisible()

    const pdfSection = screen.getByRole('region', { name: 'PDF tools' })
    const imageSection = screen.getByRole('region', { name: 'Image tools' })
    expect(within(pdfSection).getAllByRole('article')).toHaveLength(6)
    expect(within(imageSection).getAllByRole('article')).toHaveLength(4)

    for (const title of [
      'Merge PDF',
      'Split PDF',
      'Rotate PDF',
      'Remove pages',
      'Extract pages',
      'PDF to images',
      'Convert image',
      'Resize image',
      'Compress image',
      'Images to PDF',
    ]) {
      expect(screen.getAllByRole('heading', { level: 3, name: title })).toHaveLength(1)
    }
  })

  it('does not expose an operational conversion form or file input', () => {
    render(<App checkHealth={pendingHealth} />)
    expect(screen.queryByRole('form')).not.toBeInTheDocument()
    expect(document.querySelector('input[type="file"]')).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
