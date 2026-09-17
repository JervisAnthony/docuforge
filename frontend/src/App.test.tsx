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
    const batchSection = screen.getByRole('region', { name: 'Batch tools' })
    const imageSection = screen.getByRole('region', { name: 'Image tools' })
    const officeSection = screen.getByRole('region', { name: 'Office tools' })
    const ocrSection = screen.getByRole('region', { name: 'OCR tools' })
    expect(within(pdfSection).getAllByRole('article')).toHaveLength(6)
    expect(within(batchSection).getAllByRole('article')).toHaveLength(4)
    expect(within(imageSection).getAllByRole('article')).toHaveLength(4)
    expect(within(officeSection).getAllByRole('article')).toHaveLength(3)
    expect(within(ocrSection).getAllByRole('article')).toHaveLength(3)

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
      'Word to PDF',
      'PowerPoint to PDF',
      'Excel to PDF',
      'Image to Text',
      'Scanned PDF to Text',
      'Searchable PDF',
      'Batch image convert',
      'Batch image resize',
      'Batch image compress',
      'Batch Office to PDF',
    ]) {
      expect(screen.getAllByRole('heading', { level: 3, name: title })).toHaveLength(1)
    }
    expect(within(pdfSection).getAllByRole('button', { name: /^Open / })).toHaveLength(6)
    expect(within(batchSection).getAllByRole('button', { name: /^Open / })).toHaveLength(4)
    expect(within(imageSection).getAllByRole('button', { name: /^Open / })).toHaveLength(4)
    expect(within(officeSection).getAllByRole('button', { name: /^Open / })).toHaveLength(3)
    expect(within(ocrSection).getAllByRole('button', { name: /^Open / })).toHaveLength(3)
    expect(screen.getAllByRole('button', { name: /^Open / })).toHaveLength(20)
  })

  it('does not expose a form until a tool is selected', () => {
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

  it('opens an image workflow, focuses its heading, and returns to the catalog', async () => {
    const user = userEvent.setup()
    render(<App checkHealth={pendingHealth} />)

    await user.click(screen.getByRole('button', { name: 'Open Resize image' }))
    const heading = screen.getByRole('heading', { level: 1, name: 'Resize image' })
    expect(heading).toHaveFocus()
    expect(screen.getByRole('form', { name: 'Resize image form' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'PDF tools' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '← Back to tools' }))
    expect(screen.getByRole('region', { name: 'Image tools' })).toBeVisible()
  })

  it('opens an Office workflow, focuses its heading, and returns to the catalog', async () => {
    const user = userEvent.setup()
    render(<App checkHealth={pendingHealth} />)
    await user.click(screen.getByRole('button', { name: 'Open Word to PDF' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Word to PDF' })).toHaveFocus()
    expect(screen.getByRole('form', { name: 'Word to PDF form' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '← Back to tools' }))
    expect(screen.getByRole('region', { name: 'Office tools' })).toBeVisible()
  })

  it('opens an OCR workflow, focuses its heading, and returns to the catalog', async () => {
    const user = userEvent.setup()
    render(<App checkHealth={pendingHealth} />)
    await user.click(screen.getByRole('button', { name: 'Open Image to Text' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Image to Text' })).toHaveFocus()
    expect(screen.getByRole('form', { name: 'Image to Text form' })).toBeInTheDocument()
    expect(screen.getByText('OCR requires the server OCR engine to be available.')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /Back to tools/ }))
    expect(screen.getByRole('region', { name: 'OCR tools' })).toBeVisible()
  })

  it.each([
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
    'Word to PDF',
    'PowerPoint to PDF',
    'Excel to PDF',
    'Image to Text',
    'Scanned PDF to Text',
    'Searchable PDF',
  ])('opens the operational %s card', async (toolName) => {
    const user = userEvent.setup()
    render(<App checkHealth={pendingHealth} />)
    await user.click(screen.getByRole('button', { name: `Open ${toolName}` }))
    expect(screen.getByRole('heading', { level: 1, name: toolName })).toBeVisible()
    expect(screen.getByRole('form')).toBeInTheDocument()
  })

  it('does not leak selected files between image workspaces', async () => {
    const user = userEvent.setup()
    render(<App checkHealth={pendingHealth} />)
    await user.click(screen.getByRole('button', { name: 'Open Convert image' }))
    await user.upload(
      screen.getByLabelText('Image file'),
      new File(['image'], 'photo.jpg', { type: 'image/jpeg' }),
    )
    expect(screen.getByText('photo.jpg')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '← Back to tools' }))
    await user.click(screen.getByRole('button', { name: 'Open Resize image' }))
    expect(screen.queryByText('photo.jpg')).not.toBeInTheDocument()
  })
})
