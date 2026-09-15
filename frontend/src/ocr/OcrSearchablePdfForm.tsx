import { useState } from 'react'
import { FilePicker } from '../components/FilePicker'
import { SelectedFile } from '../components/SelectedFile'
import { WorkflowStatus } from '../components/WorkflowStatus'
import { toolById } from '../tools/catalog'
import type { MultipartRequestClient } from '../workflows/useSubmission'
import { useSubmission } from '../workflows/useSubmission'
import { hasAllowedOcrExtension, ocrFallbackFilename, ocrInputConfig } from './config'

interface OcrSearchablePdfFormProps {
  client?: MultipartRequestClient
}

const toolId = 'ocr-pdf-to-searchable-pdf'

export function OcrSearchablePdfForm({ client }: OcrSearchablePdfFormProps) {
  const tool = toolById(toolId)
  const config = ocrInputConfig[toolId]
  const [file, setFile] = useState<File | null>(null)
  const submission = useSubmission(
    client, 'The document could not be processed with OCR. Please try again.',
  )
  const valid = Boolean(file && hasAllowedOcrExtension(file.name, config.extensions))
  const fileError = file && !valid ? 'Choose a .pdf file.' : null

  function updateFile(files: File[]) {
    const nextFile = files.length === 1 ? files[0] : null
    setFile(nextFile)
    submission.reset(Boolean(nextFile && hasAllowedOcrExtension(nextFile.name, config.extensions)))
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || !valid) return
    const formData = new FormData()
    formData.append('file', file)
    await submission.submit(
      tool.endpoint, formData, ocrFallbackFilename(file.name, '-searchable.pdf'),
    )
  }

  const submitting = submission.feedback.status === 'submitting'
  return (
    <form className="workflow-form" aria-label={`${tool.title} form`} onSubmit={handleSubmit} noValidate>
      <FilePicker
        id={`${toolId}-file`}
        label={config.label}
        files={file ? [file] : []}
        accept={config.accept}
        disabled={submitting}
        error={fileError}
        helpText={config.help}
        onFiles={updateFile}
      />
      {file ? <SelectedFile file={file} onClear={() => updateFile([])} disabled={submitting} /> : null}
      <div className="workflow-actions">
        <button className="button button--primary" type="submit" disabled={!valid || submitting}>
          {submitting ? 'Processing…' : 'Make searchable'}
        </button>
      </div>
      <WorkflowStatus feedback={submission.feedback} />
    </form>
  )
}
