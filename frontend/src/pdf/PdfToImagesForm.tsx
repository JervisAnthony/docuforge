import { useState } from 'react'
import { FieldError } from '../components/FieldError'
import { FilePicker } from '../components/FilePicker'
import { SelectedFile } from '../components/SelectedFile'
import { WorkflowStatus } from '../components/WorkflowStatus'
import { toolById } from '../tools/catalog'
import { isPdfFile } from './fileUtils'
import type { PdfFormProps } from './types'
import { usePdfSubmission } from './usePdfSubmission'

const tool = toolById('pdf-to-images')
const imageFormats = [
  ['jpeg', 'JPEG'],
  ['png', 'PNG'],
  ['webp', 'WebP'],
  ['bmp', 'BMP'],
  ['tiff', 'TIFF'],
] as const

function validateDpi(value: string): string | null {
  if (!/^\d+$/.test(value)) return 'DPI must be a whole number from 72 through 300.'
  const dpi = Number(value)
  return dpi >= 72 && dpi <= 300
    ? null
    : 'DPI must be a whole number from 72 through 300.'
}

export function PdfToImagesForm({ client }: PdfFormProps) {
  const [file, setFile] = useState<File | null>(null)
  const [format, setFormat] = useState<(typeof imageFormats)[number][0]>('png')
  const [dpi, setDpi] = useState('150')
  const submission = usePdfSubmission(client)
  const dpiError = validateDpi(dpi)
  const fileValid = Boolean(file && isPdfFile(file))
  const valid = fileValid && !dpiError
  const fileError = file && !isPdfFile(file) ? 'Choose a file with a .pdf extension.' : null

  function resetFeedback(nextFile: File | null, nextDpi: string) {
    submission.reset(Boolean(nextFile && isPdfFile(nextFile) && !validateDpi(nextDpi)))
  }

  function updateFile(files: File[]) {
    const nextFile = files[0] ?? null
    setFile(nextFile)
    resetFeedback(nextFile, dpi)
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || !valid) return
    const formData = new FormData()
    formData.append('file', file)
    formData.append('format', format)
    formData.append('dpi', dpi)
    await submission.submit(tool.endpoint, formData, 'pdf-images.zip')
  }

  const submitting = submission.feedback.status === 'submitting'
  return (
    <form
      className="workflow-form"
      aria-label="PDF to images form"
      onSubmit={handleSubmit}
      noValidate
    >
      <FilePicker
        id="pdf-images-file"
        label="PDF file"
        files={file ? [file] : []}
        disabled={submitting}
        error={fileError}
        helpText="One image per page will be returned inside a ZIP archive."
        onFiles={updateFile}
      />
      {file ? <SelectedFile file={file} onClear={() => updateFile([])} disabled={submitting} /> : null}

      <div className="form-field-row">
        <div className="form-field">
          <label htmlFor="pdf-images-format">Image format</label>
          <select
            id="pdf-images-format"
            value={format}
            disabled={submitting}
            onChange={(event) => {
              setFormat(event.currentTarget.value as (typeof imageFormats)[number][0])
              submission.reset(valid)
            }}
          >
            {imageFormats.map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="pdf-images-dpi">Resolution (DPI)</label>
          <p className="field-help" id="pdf-images-dpi-help">
            Higher DPI creates larger, sharper images.
          </p>
          <input
            id="pdf-images-dpi"
            type="number"
            min="72"
            max="300"
            step="1"
            value={dpi}
            disabled={submitting}
            aria-invalid={dpiError ? 'true' : undefined}
            aria-describedby={`pdf-images-dpi-help${dpiError ? ' pdf-images-dpi-error' : ''}`}
            onChange={(event) => {
              const nextDpi = event.currentTarget.value
              setDpi(nextDpi)
              resetFeedback(file, nextDpi)
            }}
          />
          <FieldError id="pdf-images-dpi-error" message={dpiError} />
        </div>
      </div>

      <div className="workflow-actions">
        <button className="button button--primary" type="submit" disabled={!valid || submitting}>
          {submitting ? 'Processing…' : 'Convert PDF to images'}
        </button>
      </div>
      <WorkflowStatus feedback={submission.feedback} />
    </form>
  )
}
