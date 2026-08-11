import { useState } from 'react'
import { FilePicker } from '../components/FilePicker'
import { WorkflowStatus } from '../components/WorkflowStatus'
import { toolById } from '../tools/catalog'
import { formatFileSize, isPdfFile } from './fileUtils'
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

  function moveFile(index: number, direction: -1 | 1) {
    const nextFiles = [...files]
    const target = index + direction
    ;[nextFiles[index], nextFiles[target]] = [nextFiles[target], nextFiles[index]]
    updateFiles(nextFiles)
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

      {files.length ? (
        <div className="selected-files" aria-labelledby="merge-order-heading">
          <div className="selected-files__header">
            <h2 id="merge-order-heading">Merge order</h2>
            <button
              type="button"
              className="button button--quiet"
              onClick={() => updateFiles([])}
              disabled={submitting}
            >
              Clear all
            </button>
          </div>
          <ol>
            {files.map((file, index) => (
              <li key={`${file.name}-${file.size}-${file.lastModified}-${index}`}>
                <div className="selected-files__name">
                  <strong>{file.name}</strong>
                  <span>{formatFileSize(file.size)}</span>
                </div>
                <div className="selected-files__actions">
                  <button
                    type="button"
                    className="button button--quiet"
                    aria-label={`Move ${file.name} up`}
                    disabled={index === 0 || submitting}
                    onClick={() => moveFile(index, -1)}
                  >
                    Move up
                  </button>
                  <button
                    type="button"
                    className="button button--quiet"
                    aria-label={`Move ${file.name} down`}
                    disabled={index === files.length - 1 || submitting}
                    onClick={() => moveFile(index, 1)}
                  >
                    Move down
                  </button>
                  <button
                    type="button"
                    className="button button--quiet button--danger"
                    aria-label={`Remove ${file.name}`}
                    disabled={submitting}
                    onClick={() => updateFiles(files.filter((_, itemIndex) => itemIndex !== index))}
                  >
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      <div className="workflow-actions">
        <button className="button button--primary" type="submit" disabled={!valid || submitting}>
          {submitting ? 'Processing…' : 'Merge PDFs'}
        </button>
      </div>
      <WorkflowStatus feedback={submission.feedback} />
    </form>
  )
}
