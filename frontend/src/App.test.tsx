import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
    expect(within(pdfSection).getAllByRole('button', { name: /^Open / })).toHaveLength(6)
    expect(within(imageSection).queryByRole('button')).not.toBeInTheDocument()
  })

  it('does not expose a form until a PDF tool is selected', () => {
    render(<App checkHealth={pendingHealth} />)
    expect(screen.queryByRole('form')).not.toBeInTheDocument()
    expect(document.querySelector('input[type="file"]')).not.toBeInTheDocument()
  })

  it('opens a PDF workflow, focuses its heading, and returns to the catalog', async () => {
    const user = userEvent.setup()
    render(<App checkHealth={pendingHealth} />)

    await user.click(screen.getByRole('button', { name: 'Open Merge PDF' }))
    const heading = screen.getByRole('heading', { level: 1, name: 'Merge PDF' })
    expect(heading).toHaveFocus()
    expect(screen.getByRole('form')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Image tools' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '← Back to tools' }))
    expect(screen.getByRole('region', { name: 'PDF tools' })).toBeVisible()
    expect(screen.getByRole('region', { name: 'Image tools' })).toBeVisible()
  })
})
