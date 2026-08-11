import { useState } from 'react'
import { FieldError } from '../components/FieldError'
import { FilePicker } from '../components/FilePicker'
import { SelectedFile } from '../components/SelectedFile'
import { WorkflowStatus } from '../components/WorkflowStatus'
import { toolById } from '../tools/catalog'
import { useSubmission } from '../workflows/useSubmission'
import {
  IMAGE_FORMAT_SUFFIX,
  RASTER_IMAGE_ACCEPT,
  imageFormatFromFilename,
  isRasterImageFile,
} from './formats'
import type { ImageFormat } from './formats'
import { ImageFormatField } from './ImageFormatField'
import { parsePositiveInteger } from './integer'
import type { ImageFormProps } from './types'

const tool = toolById('image-resize')

export function ResizeImageForm({ client }: ImageFormProps) {
  const [file, setFile] = useState<File | null>(null)
  const [format, setFormat] = useState<ImageFormat | ''>('')
  const [maxWidth, setMaxWidth] = useState('')
  const [maxHeight, setMaxHeight] = useState('')
  const [allowUpscale, setAllowUpscale] = useState(false)
  const submission = useSubmission(client, 'The image could not be processed. Please try again.')
  const widthError = integerFieldError(maxWidth, 'Maximum width')
  const heightError = integerFieldError(maxHeight, 'Maximum height')
  const dimensionsError = !maxWidth && !maxHeight ? 'Enter a maximum width or height.' : null
  const fileValid = Boolean(file && isRasterImageFile(file))
  const valid = fileValid && Boolean(format) && !widthError && !heightError && !dimensionsError
  const fileError = file && !isRasterImageFile(file) ? 'Choose a supported image file.' : null

  function resetFeedback(
    nextFile: File | null,
    nextFormat: ImageFormat | '',
    width: string,
    height: string,
  ) {
    submission.reset(
      Boolean(
        nextFile &&
          isRasterImageFile(nextFile) &&
          nextFormat &&
          !integerFieldError(width, 'Maximum width') &&
          !integerFieldError(height, 'Maximum height') &&
          (width || height),
      ),
    )
  }

  function updateFile(files: File[]) {
    const nextFile = files[0] ?? null
    const nextFormat = nextFile ? (imageFormatFromFilename(nextFile.name) ?? '') : ''
    setFile(nextFile)
    setFormat(nextFormat)
    resetFeedback(nextFile, nextFormat, maxWidth, maxHeight)
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || !format || !valid) return
    const formData = new FormData()
    formData.append('file', file)
    formData.append('format', format)
    if (maxWidth) formData.append('max_width', maxWidth)
    if (maxHeight) formData.append('max_height', maxHeight)
    formData.append('allow_upscale', allowUpscale ? 'true' : 'false')
    await submission.submit(
      tool.endpoint,
      formData,
      `resized-image.${IMAGE_FORMAT_SUFFIX[format]}`,
    )
  }

  const submitting = submission.feedback.status === 'submitting'
  return (
    <form className="workflow-form" aria-label="Resize image form" onSubmit={handleSubmit} noValidate>
      <FilePicker
        id="resize-image-file"
        label="Image file"
        files={file ? [file] : []}
        accept={RASTER_IMAGE_ACCEPT}
        disabled={submitting}
        error={fileError}
        onFiles={updateFile}
      />
      {file ? <SelectedFile file={file} onClear={() => updateFile([])} disabled={submitting} /> : null}
      <ImageFormatField
        id="resize-image-format"
        value={format}
        disabled={submitting}
        onChange={(nextFormat) => {
          setFormat(nextFormat)
          resetFeedback(file, nextFormat, maxWidth, maxHeight)
        }}
      />
      <div className="form-field">
        <p className="field-help" id="resize-dimensions-help">
          Aspect ratio is preserved and the image is not cropped. Provide one or both limits.
        </p>
        <div className="form-field-row">
          <div className="form-field">
            <label htmlFor="resize-max-width">Maximum width</label>
            <input
              id="resize-max-width"
              type="number"
              min="1"
              step="1"
              inputMode="numeric"
              value={maxWidth}
              disabled={submitting}
              aria-invalid={widthError || (file && dimensionsError) ? 'true' : undefined}
              aria-describedby={`resize-dimensions-help${widthError ? ' resize-max-width-error' : ''}${file && dimensionsError ? ' resize-dimensions-error' : ''}`}
              onChange={(event) => {
                const value = event.currentTarget.value
                setMaxWidth(value)
                resetFeedback(file, format, value, maxHeight)
              }}
            />
            <FieldError id="resize-max-width-error" message={widthError} />
          </div>
          <div className="form-field">
            <label htmlFor="resize-max-height">Maximum height</label>
            <input
              id="resize-max-height"
              type="number"
              min="1"
              step="1"
              inputMode="numeric"
              value={maxHeight}
              disabled={submitting}
              aria-invalid={heightError || (file && dimensionsError) ? 'true' : undefined}
              aria-describedby={`resize-dimensions-help${heightError ? ' resize-max-height-error' : ''}${file && dimensionsError ? ' resize-dimensions-error' : ''}`}
              onChange={(event) => {
                const value = event.currentTarget.value
                setMaxHeight(value)
                resetFeedback(file, format, maxWidth, value)
              }}
            />
            <FieldError id="resize-max-height-error" message={heightError} />
          </div>
        </div>
        <FieldError id="resize-dimensions-error" message={file ? dimensionsError : null} />
      </div>
      <div className="checkbox-control">
        <input
          id="resize-allow-upscale"
          type="checkbox"
          checked={allowUpscale}
          disabled={submitting}
          aria-describedby="resize-allow-upscale-help"
          onChange={(event) => {
            setAllowUpscale(event.currentTarget.checked)
            submission.reset(valid)
          }}
        />
        <span>
          <label htmlFor="resize-allow-upscale">Allow upscaling</label>
          <small id="resize-allow-upscale-help">
            Off by default; enable only when a larger output is wanted.
          </small>
        </span>
      </div>
      <div className="workflow-actions">
        <button className="button button--primary" type="submit" disabled={!valid || submitting}>
          {submitting ? 'Processing…' : 'Resize image'}
        </button>
      </div>
      <WorkflowStatus feedback={submission.feedback} />
    </form>
  )
}

function integerFieldError(value: string, label: string): string | null {
  return value && parsePositiveInteger(value) === null
    ? `${label} must be a positive whole number.`
    : null
}
