import { useState } from 'react'
import { FilePicker } from '../components/FilePicker'
import { OrderedFileList } from '../components/OrderedFileList'
import { WorkflowStatus } from '../components/WorkflowStatus'
import { toolById } from '../tools/catalog'
import { useSubmission } from '../workflows/useSubmission'
import { IMAGE_TO_PDF_ACCEPT, isImageToPdfFile } from './formats'
import type { ImageFormProps } from './types'

const tool = toolById('images-to-pdf')

export function ImagesToPdfForm({ client }: ImageFormProps) {
  const [files, setFiles] = useState<File[]>([])
  const submission = useSubmission(client, 'The images could not be processed. Please try again.')
  const invalidFile = files.some((file) => !isImageToPdfFile(file))
  const valid = files.length >= 1 && !invalidFile
  const fileError = invalidFile
    ? 'Choose JPEG, PNG, BMP, or TIFF files; WebP is not supported for this workflow.'
    : null

  function updateFiles(nextFiles: File[]) {
    setFiles(nextFiles)
    submission.reset(nextFiles.length >= 1 && nextFiles.every(isImageToPdfFile))
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!valid) return
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))
    await submission.submit(tool.endpoint, formData, 'images.pdf')
  }

  const submitting = submission.feedback.status === 'submitting'
  return (
    <form className="workflow-form" aria-label="Images to PDF form" onSubmit={handleSubmit} noValidate>
      <FilePicker
        id="images-to-pdf-files"
        label="Image files"
        files={files}
        accept={IMAGE_TO_PDF_ACCEPT}
        multiple
        disabled={submitting}
        error={fileError}
        helpText="Choose one or more images. PDF pages follow the displayed order."
        onFiles={updateFiles}
      />
      <OrderedFileList
        files={files}
        heading="PDF page order"
        headingId="images-to-pdf-order-heading"
        onFiles={updateFiles}
        disabled={submitting}
      />
      <div className="workflow-actions">
        <button className="button button--primary" type="submit" disabled={!valid || submitting}>
          {submitting ? 'Processing…' : 'Create PDF'}
        </button>
      </div>
      <WorkflowStatus feedback={submission.feedback} />
    </form>
  )
}
