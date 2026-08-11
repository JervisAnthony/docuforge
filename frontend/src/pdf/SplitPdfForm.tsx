import { useState } from 'react'
import { FilePicker } from '../components/FilePicker'
import { SelectedFile } from '../components/SelectedFile'
import { WorkflowStatus } from '../components/WorkflowStatus'
import { toolById } from '../tools/catalog'
import { isPdfFile } from './fileUtils'
import type { PdfFormProps } from './types'
import { usePdfSubmission } from './usePdfSubmission'

const tool = toolById('pdf-split')

export function SplitPdfForm({ client }: PdfFormProps) {
  const [file, setFile] = useState<File | null>(null)
  const submission = usePdfSubmission(client)
  const valid = Boolean(file && isPdfFile(file))
  const error = file && !isPdfFile(file) ? 'Choose a file with a .pdf extension.' : null

  function updateFile(files: File[]) {
    const nextFile = files[0] ?? null
    setFile(nextFile)
    submission.reset(Boolean(nextFile && isPdfFile(nextFile)))
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || !valid) return
    const formData = new FormData()
    formData.append('file', file)
    await submission.submit(tool.endpoint, formData, 'split-pages.zip')
  }

  const submitting = submission.feedback.status === 'submitting'
  return (
    <form className="workflow-form" aria-label="Split PDF form" onSubmit={handleSubmit} noValidate>
      <FilePicker
        id="split-file"
        label="PDF file"
        files={file ? [file] : []}
        disabled={submitting}
        error={error}
        helpText="Every page becomes a separate PDF inside one ZIP download."
        onFiles={updateFile}
      />
      {file ? <SelectedFile file={file} onClear={() => updateFile([])} disabled={submitting} /> : null}
      <div className="workflow-actions">
        <button className="button button--primary" type="submit" disabled={!valid || submitting}>
          {submitting ? 'Processing…' : 'Split PDF'}
        </button>
      </div>
      <WorkflowStatus feedback={submission.feedback} />
    </form>
  )
}
