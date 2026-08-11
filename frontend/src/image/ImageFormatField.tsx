import { FieldError } from '../components/FieldError'
import { IMAGE_FORMATS, isImageFormat } from './formats'
import type { ImageFormat } from './formats'

interface ImageFormatFieldProps {
  id: string
  value: ImageFormat | ''
  onChange: (format: ImageFormat) => void
  disabled?: boolean
  error?: string | null
}

export function ImageFormatField({
  id,
  value,
  onChange,
  disabled = false,
  error = null,
}: ImageFormatFieldProps) {
  const errorId = `${id}-error`
  return (
    <div className="form-field">
      <label htmlFor={id}>Target format</label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={error ? errorId : undefined}
        onChange={(event) => {
          if (isImageFormat(event.currentTarget.value)) {
            onChange(event.currentTarget.value)
          }
        }}
      >
        <option value="" disabled>
          Choose a format
        </option>
        {IMAGE_FORMATS.map((format) => (
          <option value={format.value} key={format.value}>
            {format.label}
          </option>
        ))}
      </select>
      <FieldError id={errorId} message={error} />
    </div>
  )
}
