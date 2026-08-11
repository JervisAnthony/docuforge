import { useState } from 'react'
import { FilePicker } from '../components/FilePicker'
import { OrderedFileList } from '../components/OrderedFileList'
import { WorkflowStatus } from '../components/WorkflowStatus'
import { toolById } from '../tools/catalog'
import { isPdfFile } from './fileUtils'
import type { PdfFormProps } from './types'
import { usePdfSubmission } from './usePdfSubmission'

const tool = toolById('pdf-merge')

export function MergePdfForm({ client }: PdfFormProps) {
  const [files, setFiles] = useState<File[]>([])
  const submission = usePdfSubmission(client)
  const invalidFile = files.some((file) => !isPdfFile(file))
  const valid = files.length >= 2 && !invalidFile
  const validationMessage = invalidFile
    ? 'Choose files with a .pdf extension.'
    : files.length === 1
      ? 'Select at least two PDF files.'
      : null

  function updateFiles(nextFiles: File[]) {
    setFiles(nextFiles)
    submission.reset(nextFiles.length >= 2 && nextFiles.every(isPdfFile))
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!valid) return
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))
    await submission.submit(tool.endpoint, formData, 'merged.pdf')
  }

  const submitting = submission.feedback.status === 'submitting'
  return (
    <form className="workflow-form" aria-label="Merge PDF form" onSubmit={handleSubmit} noValidate>
      <FilePicker
        id="merge-files"
        label="PDF files"
        files={files}
        multiple
        disabled={submitting}
        error={validationMessage}
        helpText="Choose at least two PDFs. They will be merged in the order shown."
        onFiles={updateFiles}
      />

      <OrderedFileList
        files={files}
        heading="Merge order"
        headingId="merge-order-heading"
        onFiles={updateFiles}
        disabled={submitting}
      />

      <div className="workflow-actions">
        <button className="button button--primary" type="submit" disabled={!valid || submitting}>
          {submitting ? 'Processing…' : 'Merge PDFs'}
        </button>
      </div>
      <WorkflowStatus feedback={submission.feedback} />
    </form>
  )
}
