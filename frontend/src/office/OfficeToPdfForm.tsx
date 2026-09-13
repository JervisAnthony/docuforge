import { useState } from 'react'
import { FilePicker } from '../components/FilePicker'
import { SelectedFile } from '../components/SelectedFile'
import { WorkflowStatus } from '../components/WorkflowStatus'
import { toolById } from '../tools/catalog'
import type { OfficeToolId } from '../tools/types'
import { useSubmission } from '../workflows/useSubmission'
import type { MultipartRequestClient } from '../workflows/useSubmission'
import { officeConfig } from './config'

interface OfficeToPdfFormProps {
  toolId: OfficeToolId
  client?: MultipartRequestClient
}

export function OfficeToPdfForm({ toolId, client }: OfficeToPdfFormProps) {
  const tool = toolById(toolId)
  const config = officeConfig[toolId]
  const [file, setFile] = useState<File | null>(null)
  const submission = useSubmission(client, 'The Office document could not be converted. Please try again.')
  const valid = Boolean(file && file.name.toLowerCase().endsWith(config.extension))
  const fileError = file && !valid ? `Choose a ${config.extension} file.` : null

  function updateFile(files: File[]) {
    const nextFile = files[0] ?? null
    setFile(nextFile)
    submission.reset(Boolean(nextFile?.name.toLowerCase().endsWith(config.extension)))
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || !valid) return
    const formData = new FormData()
    formData.append('file', file)
    await submission.submit(tool.endpoint, formData, `${file.name.slice(0, -config.extension.length)}.pdf`)
  }

  const submitting = submission.feedback.status === 'submitting'
  return (
    <form className="workflow-form" aria-label={`${tool.title} form`} onSubmit={handleSubmit} noValidate>
      <FilePicker
        id={`${toolId}-file`}
        label={config.label}
        files={file ? [file] : []}
        accept={config.extension}
        disabled={submitting}
        error={fileError}
        helpText={`Choose one ${config.extension} file.`}
        onFiles={updateFile}
      />
      {file ? <SelectedFile file={file} onClear={() => updateFile([])} disabled={submitting} /> : null}
      <div className="workflow-actions">
        <button className="button button--primary" type="submit" disabled={!valid || submitting}>
          {submitting ? 'Processing…' : 'Convert to PDF'}
        </button>
      </div>
      <WorkflowStatus feedback={submission.feedback} />
    </form>
  )
}
