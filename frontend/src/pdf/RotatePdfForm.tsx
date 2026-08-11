import { useState } from 'react'
import { FieldError } from '../components/FieldError'
import { FilePicker } from '../components/FilePicker'
import { SelectedFile } from '../components/SelectedFile'
import { WorkflowStatus } from '../components/WorkflowStatus'
import { toolById } from '../tools/catalog'
import { isPdfFile } from './fileUtils'
import type { PdfFormProps } from './types'
import { usePdfSubmission } from './usePdfSubmission'

type RotationDegrees = '90' | '180' | '270'

interface RotationRow {
  id: number
  page: string
  degrees: RotationDegrees
}

const tool = toolById('pdf-rotate')
let nextRowId = 2

function validateRows(rows: readonly RotationRow[]): string | null {
  if (!rows.length) return 'Add at least one rotation instruction.'
  const pages = new Set<number>()
  for (const row of rows) {
    if (!/^[1-9]\d*$/.test(row.page)) {
      return 'Every page must be a positive whole number.'
    }
    const page = Number(row.page)
    if (!Number.isSafeInteger(page)) {
      return 'A page number is too large.'
    }
    if (pages.has(page)) {
      return `Page ${page} has more than one rotation instruction.`
    }
    pages.add(page)
  }
  return null
}

function isRotationDegrees(value: string): value is RotationDegrees {
  return value === '90' || value === '180' || value === '270'
}

export function RotatePdfForm({ client }: PdfFormProps) {
  const [file, setFile] = useState<File | null>(null)
  const [rows, setRows] = useState<RotationRow[]>([
    { id: 1, page: '', degrees: '90' },
  ])
  const submission = usePdfSubmission(client)
  const rowError = validateRows(rows)
  const fileValid = Boolean(file && isPdfFile(file))
  const valid = fileValid && !rowError
  const fileError = file && !isPdfFile(file) ? 'Choose a file with a .pdf extension.' : null

  function resetFeedback(nextFile: File | null, nextRows: RotationRow[]) {
    submission.reset(Boolean(nextFile && isPdfFile(nextFile) && !validateRows(nextRows)))
  }

  function updateFile(files: File[]) {
    const nextFile = files[0] ?? null
    setFile(nextFile)
    resetFeedback(nextFile, rows)
  }

  function updateRows(nextRows: RotationRow[]) {
    setRows(nextRows)
    resetFeedback(file, nextRows)
  }

  function updateRow(id: number, update: Partial<Pick<RotationRow, 'page' | 'degrees'>>) {
    updateRows(rows.map((row) => (row.id === id ? { ...row, ...update } : row)))
  }

  function addRow() {
    updateRows([...rows, { id: nextRowId++, page: '', degrees: '90' }])
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || !valid) return
    const formData = new FormData()
    formData.append('file', file)
    rows.forEach((row) => formData.append('rotate', `${row.page}:${row.degrees}`))
    await submission.submit(tool.endpoint, formData, 'rotated.pdf')
  }

  const submitting = submission.feedback.status === 'submitting'
  return (
    <form className="workflow-form" aria-label="Rotate PDF form" onSubmit={handleSubmit} noValidate>
      <FilePicker
        id="rotate-file"
        label="PDF file"
        files={file ? [file] : []}
        disabled={submitting}
        error={fileError}
        onFiles={updateFile}
      />
      {file ? <SelectedFile file={file} onClear={() => updateFile([])} disabled={submitting} /> : null}

      <fieldset className="rotation-fieldset" aria-describedby="rotation-help rotation-error">
        <legend>Page rotations</legend>
        <p className="field-help" id="rotation-help">
          Add one instruction for each page you want to rotate. Page numbers start at 1.
        </p>
        <div className="rotation-rows">
          {rows.map((row, index) => {
            const pageInvalid = Boolean(row.page && !/^[1-9]\d*$/.test(row.page))
            return (
              <div className="rotation-row" key={row.id}>
                <div className="form-field">
                  <label htmlFor={`rotation-page-${row.id}`}>Page {index + 1}</label>
                  <input
                    id={`rotation-page-${row.id}`}
                    type="number"
                    min="1"
                    step="1"
                    inputMode="numeric"
                    value={row.page}
                    disabled={submitting}
                    aria-invalid={pageInvalid ? 'true' : undefined}
                    onChange={(event) => updateRow(row.id, { page: event.currentTarget.value })}
                  />
                </div>
                <div className="form-field">
                  <label htmlFor={`rotation-degrees-${row.id}`}>Rotation</label>
                  <select
                    id={`rotation-degrees-${row.id}`}
                    value={row.degrees}
                    disabled={submitting}
                    onChange={(event) => {
                      const value = event.currentTarget.value
                      if (isRotationDegrees(value)) {
                        updateRow(row.id, { degrees: value })
                      }
                    }}
                  >
                    <option value="90">90°</option>
                    <option value="180">180°</option>
                    <option value="270">270°</option>
                  </select>
                </div>
                <button
                  type="button"
                  className="button button--quiet button--danger rotation-row__remove"
                  aria-label={`Remove rotation row ${index + 1}`}
                  disabled={rows.length === 1 || submitting}
                  onClick={() => updateRows(rows.filter((candidate) => candidate.id !== row.id))}
                >
                  Remove
                </button>
              </div>
            )
          })}
        </div>
        <button type="button" className="button button--secondary" onClick={addRow} disabled={submitting}>
          Add page rotation
        </button>
        <FieldError id="rotation-error" message={rows.some((row) => row.page) ? rowError : null} />
      </fieldset>

      <div className="workflow-actions">
        <button className="button button--primary" type="submit" disabled={!valid || submitting}>
          {submitting ? 'Processing…' : 'Rotate PDF'}
        </button>
      </div>
      <WorkflowStatus feedback={submission.feedback} />
    </form>
  )
}
