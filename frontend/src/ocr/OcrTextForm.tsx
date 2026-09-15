import { useState } from 'react'
import { FilePicker } from '../components/FilePicker'
import { SelectedFile } from '../components/SelectedFile'
import { toolById } from '../tools/catalog'
import type { OcrToolId } from '../tools/types'
import { downloadBlob } from '../utils/download'
import type { MultipartRequestClient } from '../workflows/useSubmission'
import { hasAllowedOcrExtension, ocrFallbackFilename, ocrInputConfig } from './config'
import { useOcrTextSubmission } from './useOcrTextSubmission'

type TextToolId = Extract<OcrToolId, 'ocr-image-to-text' | 'ocr-pdf-to-text'>

interface OcrTextFormProps {
  toolId: TextToolId
  client?: MultipartRequestClient
}

export function OcrTextForm({ toolId, client }: OcrTextFormProps) {
  const tool = toolById(toolId)
  const config = ocrInputConfig[toolId]
  const [file, setFile] = useState<File | null>(null)
  const submission = useOcrTextSubmission(client)
  const valid = Boolean(file && hasAllowedOcrExtension(file.name, config.extensions))
  const fileError = file && !valid ? `Choose a supported ${config.label.toLowerCase()} file.` : null

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
    await submission.submit(tool.endpoint, formData, ocrFallbackFilename(file.name, '.txt'))
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
          {submitting ? 'Processing…' : 'Extract text'}
        </button>
      </div>
      {submission.feedback.status === 'error' ? (
        <div className="workflow-feedback workflow-feedback--error" role="alert">
          {submission.feedback.message}
        </div>
      ) : submission.feedback.status === 'submitting' ? (
        <div className="workflow-feedback" role="status">
          <span className="processing-spinner" aria-hidden="true" /> Processing…
        </div>
      ) : null}
      {submission.result ? (
        <div className="ocr-text-result" role="region" aria-label="OCR text result">
          <label htmlFor={`${toolId}-result`}>Extracted text</label>
          {submission.result.text === '' ? <p>No text was recognized in this document.</p> : null}
          <textarea id={`${toolId}-result`} readOnly value={submission.result.text} rows={12} />
          <button
            type="button"
            className="button button--secondary"
            onClick={() => downloadBlob(submission.result!.blob, submission.result!.filename)}
          >
            Download text
          </button>
        </div>
      ) : null}
    </form>
  )
}
