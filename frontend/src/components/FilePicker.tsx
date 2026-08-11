import { useEffect, useRef } from 'react'
import { FieldError } from './FieldError'

interface FilePickerProps {
  id: string
  label: string
  files: readonly File[]
  onFiles: (files: File[]) => void
  multiple?: boolean
  disabled?: boolean
  error?: string | null
  helpText?: string
}

export function FilePicker({
  id,
  label,
  files,
  onFiles,
  multiple = false,
  disabled = false,
  error = null,
  helpText,
}: FilePickerProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const descriptionId = `${id}-description`
  const errorId = `${id}-error`
  const describedBy = [helpText ? descriptionId : null, error ? errorId : null]
    .filter(Boolean)
    .join(' ')

  useEffect(() => {
    if (!files.length && inputRef.current) {
      inputRef.current.value = ''
    }
  }, [files.length])

  return (
    <div className="form-field">
      <label htmlFor={id}>{label}</label>
      {helpText ? (
        <p className="field-help" id={descriptionId}>
          {helpText}
        </p>
      ) : null}
      <input
        ref={inputRef}
        id={id}
        type="file"
        accept=".pdf,application/pdf"
        multiple={multiple}
        disabled={disabled}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={describedBy || undefined}
        onChange={(event) => onFiles(Array.from(event.currentTarget.files ?? []))}
      />
      <FieldError id={errorId} message={error} />
    </div>
  )
}
