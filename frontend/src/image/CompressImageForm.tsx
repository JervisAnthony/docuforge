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
import { parseKilobytesToBytes, parsePositiveInteger } from './integer'
import type { CompressionMode, ImageFormProps } from './types'

const tool = toolById('image-compress')

export function CompressImageForm({ client }: ImageFormProps) {
  const [file, setFile] = useState<File | null>(null)
  const [format, setFormat] = useState<ImageFormat | ''>('')
  const [mode, setMode] = useState<CompressionMode>('quality')
  const [quality, setQuality] = useState('80')
  const [targetKilobytes, setTargetKilobytes] = useState('')
  const submission = useSubmission(client, 'The image could not be processed. Please try again.')
  const fileValid = Boolean(file && isRasterImageFile(file))
  const qualityError = mode === 'quality' ? validateQuality(quality) : null
  const targetError = mode === 'max-size' ? validateTargetKilobytes(targetKilobytes) : null
  const formatError = validateCompressionFormat(format, mode, fileValid)
  const valid = fileValid && Boolean(format) && !qualityError && !targetError && !formatError
  const fileError = file && !isRasterImageFile(file) ? 'Choose a supported image file.' : null

  function isReady(
    nextFile: File | null,
    nextFormat: ImageFormat | '',
    nextMode: CompressionMode,
    nextQuality: string,
    nextTarget: string,
  ) {
    const nextFileValid = Boolean(nextFile && isRasterImageFile(nextFile))
    return Boolean(
      nextFileValid &&
        nextFormat &&
        !validateCompressionFormat(nextFormat, nextMode, nextFileValid) &&
        (nextMode === 'quality'
          ? !validateQuality(nextQuality)
          : !validateTargetKilobytes(nextTarget)),
    )
  }

  function resetFeedback(
    nextFile = file,
    nextFormat = format,
    nextMode = mode,
    nextQuality = quality,
    nextTarget = targetKilobytes,
  ) {
    submission.reset(isReady(nextFile, nextFormat, nextMode, nextQuality, nextTarget))
  }

  function updateFile(files: File[]) {
    const nextFile = files[0] ?? null
    const nextFormat = nextFile ? (imageFormatFromFilename(nextFile.name) ?? '') : ''
    setFile(nextFile)
    setFormat(nextFormat)
    resetFeedback(nextFile, nextFormat)
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || !format || !valid) return
    const formData = new FormData()
    formData.append('file', file)
    formData.append('format', format)
    if (mode === 'quality') {
      formData.append('quality', quality)
    } else {
      const maxBytes = parseKilobytesToBytes(targetKilobytes)
      if (maxBytes === null) return
      formData.append('max_bytes', String(maxBytes))
    }
    await submission.submit(
      tool.endpoint,
      formData,
      `compressed-image.${IMAGE_FORMAT_SUFFIX[format]}`,
    )
  }

  const submitting = submission.feedback.status === 'submitting'
  return (
    <form className="workflow-form" aria-label="Compress image form" onSubmit={handleSubmit} noValidate>
      <FilePicker
        id="compress-image-file"
        label="Image file"
        files={file ? [file] : []}
        accept={RASTER_IMAGE_ACCEPT}
        disabled={submitting}
        error={fileError}
        onFiles={updateFile}
      />
      {file ? <SelectedFile file={file} onClear={() => updateFile([])} disabled={submitting} /> : null}
      <ImageFormatField
        id="compress-image-format"
        value={format}
        error={formatError}
        disabled={submitting}
        onChange={(nextFormat) => {
          setFormat(nextFormat)
          resetFeedback(file, nextFormat)
        }}
      />
      <fieldset className="choice-fieldset">
        <legend>Compression mode</legend>
        <div className="choice-options">
          {(['quality', 'max-size'] as const).map((choice) => (
            <label key={choice}>
              <input
                type="radio"
                name="compression-mode"
                value={choice}
                checked={mode === choice}
                disabled={submitting}
                onChange={() => {
                  setMode(choice)
                  resetFeedback(file, format, choice)
                }}
              />
              {choice === 'quality' ? 'Quality' : 'Maximum file size'}
            </label>
          ))}
        </div>
      </fieldset>
      {mode === 'quality' ? (
        <div className="form-field">
          <label htmlFor="compress-quality">Quality</label>
          <p className="field-help" id="compress-quality-help">
            JPEG and WebP only; choose a whole number from 1 through 95.
          </p>
          <input
            id="compress-quality"
            type="number"
            min="1"
            max="95"
            step="1"
            value={quality}
            disabled={submitting}
            aria-invalid={qualityError ? 'true' : undefined}
            aria-describedby={`compress-quality-help${qualityError ? ' compress-quality-error' : ''}`}
            onChange={(event) => {
              const value = event.currentTarget.value
              setQuality(value)
              resetFeedback(file, format, mode, value)
            }}
          />
          <FieldError id="compress-quality-error" message={qualityError} />
        </div>
      ) : (
        <div className="form-field">
          <label htmlFor="compress-target-kb">Maximum size (KB)</label>
          <p className="field-help" id="compress-target-kb-help">
            1 KB = 1024 bytes. The backend guarantees the requested maximum or returns an error.
          </p>
          <input
            id="compress-target-kb"
            type="number"
            min="1"
            step="1"
            value={targetKilobytes}
            disabled={submitting}
            aria-invalid={targetError ? 'true' : undefined}
            aria-describedby={`compress-target-kb-help${targetError ? ' compress-target-kb-error' : ''}`}
            onChange={(event) => {
              const value = event.currentTarget.value
              setTargetKilobytes(value)
              resetFeedback(file, format, mode, quality, value)
            }}
          />
          <FieldError id="compress-target-kb-error" message={targetError} />
        </div>
      )}
      <div className="workflow-actions">
        <button className="button button--primary" type="submit" disabled={!valid || submitting}>
          {submitting ? 'Processing…' : 'Compress image'}
        </button>
      </div>
      <WorkflowStatus feedback={submission.feedback} />
    </form>
  )
}

function validateQuality(value: string): string | null {
  const parsed = parsePositiveInteger(value)
  return parsed !== null && parsed <= 95
    ? null
    : 'Quality must be a whole number from 1 through 95.'
}

function validateTargetKilobytes(value: string): string | null {
  return parseKilobytesToBytes(value) === null
    ? 'Maximum size must be a positive whole number of KB within the safe range.'
    : null
}

function validateCompressionFormat(
  format: ImageFormat | '',
  mode: CompressionMode,
  showRequired: boolean,
): string | null {
  if (!format) return showRequired ? 'Choose a target format.' : null
  if (mode === 'quality' && format !== 'jpeg' && format !== 'webp') {
    return 'Quality compression is available for JPEG and WebP.'
  }
  return null
}
