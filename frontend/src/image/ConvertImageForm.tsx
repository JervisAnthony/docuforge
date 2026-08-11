import { useState } from 'react'
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
import type { ImageFormProps } from './types'

const tool = toolById('image-convert')

export function ConvertImageForm({ client }: ImageFormProps) {
  const [file, setFile] = useState<File | null>(null)
  const [format, setFormat] = useState<ImageFormat | ''>('')
  const submission = useSubmission(client, 'The image could not be processed. Please try again.')
  const fileValid = Boolean(file && isRasterImageFile(file))
  const valid = fileValid && Boolean(format)
  const fileError = file && !isRasterImageFile(file) ? supportedImageMessage() : null
  const formatError = fileValid && !format ? 'Choose a target format.' : null

  function resetFeedback(nextFile: File | null, nextFormat: ImageFormat | '') {
    submission.reset(Boolean(nextFile && isRasterImageFile(nextFile) && nextFormat))
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
    await submission.submit(
      tool.endpoint,
      formData,
      `converted-image.${IMAGE_FORMAT_SUFFIX[format]}`,
    )
  }

  const submitting = submission.feedback.status === 'submitting'
  return (
    <form className="workflow-form" aria-label="Convert image form" onSubmit={handleSubmit} noValidate>
      <FilePicker
        id="convert-image-file"
        label="Image file"
        files={file ? [file] : []}
        accept={RASTER_IMAGE_ACCEPT}
        disabled={submitting}
        error={fileError}
        helpText="Choose a JPEG, PNG, WebP, BMP, or TIFF image."
        onFiles={updateFile}
      />
      {file ? <SelectedFile file={file} onClear={() => updateFile([])} disabled={submitting} /> : null}
      <ImageFormatField
        id="convert-image-format"
        value={format}
        error={formatError}
        disabled={submitting}
        onChange={(nextFormat) => {
          setFormat(nextFormat)
          resetFeedback(file, nextFormat)
        }}
      />
      <div className="workflow-actions">
        <button className="button button--primary" type="submit" disabled={!valid || submitting}>
          {submitting ? 'Processing…' : 'Convert image'}
        </button>
      </div>
      <WorkflowStatus feedback={submission.feedback} />
    </form>
  )
}

function supportedImageMessage() {
  return 'Choose a JPEG, PNG, WebP, BMP, or TIFF file.'
}
