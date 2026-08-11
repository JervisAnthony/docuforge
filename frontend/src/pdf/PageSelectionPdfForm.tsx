import { useState } from 'react'
import { FieldError } from '../components/FieldError'
import { FilePicker } from '../components/FilePicker'
import { SelectedFile } from '../components/SelectedFile'
import { WorkflowStatus } from '../components/WorkflowStatus'
import { toolById } from '../tools/catalog'
import type { PdfToolId } from '../tools/types'
import { isPdfFile } from './fileUtils'
import { parsePageList } from './pageList'
import type { PdfFormProps } from './types'
import { usePdfSubmission } from './usePdfSubmission'

interface PageSelectionPdfFormProps extends PdfFormProps {
  operation: 'remove' | 'extract'
}

const operationConfig: Record<
  PageSelectionPdfFormProps['operation'],
  {
    toolId: PdfToolId
    action: string
    fallback: string
    help: string
  }
> = {
  remove: {
    toolId: 'pdf-remove-pages',
    action: 'Remove pages',
    fallback: 'trimmed.pdf',
    help: 'Enter pages to remove, separated by commas.',
  },
  extract: {
    toolId: 'pdf-extract-pages',
    action: 'Extract pages',
    fallback: 'extracted.pdf',
    help: 'Enter pages in the exact order they should appear in the new PDF.',
  },
}

export function PageSelectionPdfForm({ operation, client }: PageSelectionPdfFormProps) {
  const config = operationConfig[operation]
  const tool = toolById(config.toolId)
  const [file, setFile] = useState<File | null>(null)
  const [pageInput, setPageInput] = useState('')
  const submission = usePdfSubmission(client)
  const pageResult = parsePageList(pageInput)
  const fileValid = Boolean(file && isPdfFile(file))
  const valid = fileValid && pageResult.ok
  const pageError = pageInput && !pageResult.ok ? pageResult.message : null
  const fileError = file && !isPdfFile(file) ? 'Choose a file with a .pdf extension.' : null

  function resetFeedback(nextFile: File | null, nextInput: string) {
    submission.reset(Boolean(nextFile && isPdfFile(nextFile) && parsePageList(nextInput).ok))
  }

  function updateFile(files: File[]) {
    const nextFile = files[0] ?? null
    setFile(nextFile)
    resetFeedback(nextFile, pageInput)
  }

  function updatePages(value: string) {
    setPageInput(value)
    resetFeedback(file, value)
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || !fileValid || !pageResult.ok) return
    const formData = new FormData()
    formData.append('file', file)
    pageResult.pages.forEach((page) => formData.append('page', String(page)))
    await submission.submit(tool.endpoint, formData, config.fallback)
  }

  const submitting = submission.feedback.status === 'submitting'
  const pageErrorId = `${operation}-pages-error`
  const pageHelpId = `${operation}-pages-help`
  return (
    <form
      className="workflow-form"
      aria-label={`${config.action} form`}
      onSubmit={handleSubmit}
      noValidate
    >
      <FilePicker
        id={`${operation}-file`}
        label="PDF file"
        files={file ? [file] : []}
        disabled={submitting}
        error={fileError}
        onFiles={updateFile}
      />
      {file ? <SelectedFile file={file} onClear={() => updateFile([])} disabled={submitting} /> : null}
      <div className="form-field">
        <label htmlFor={`${operation}-pages`}>Page numbers</label>
        <p className="field-help" id={pageHelpId}>
          {config.help} Use positive whole numbers such as 2, 4, 7. Ranges are not supported.
        </p>
        <input
          id={`${operation}-pages`}
          type="text"
          inputMode="numeric"
          value={pageInput}
          disabled={submitting}
          aria-invalid={pageError ? 'true' : undefined}
          aria-describedby={`${pageHelpId}${pageError ? ` ${pageErrorId}` : ''}`}
          onChange={(event) => updatePages(event.currentTarget.value)}
        />
        <FieldError id={pageErrorId} message={pageError} />
      </div>
      <div className="workflow-actions">
        <button className="button button--primary" type="submit" disabled={!valid || submitting}>
          {submitting ? 'Processing…' : config.action}
        </button>
      </div>
      <WorkflowStatus feedback={submission.feedback} />
    </form>
  )
}
