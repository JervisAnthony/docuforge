interface FieldErrorProps {
  id: string
  message: string | null
}

export function FieldError({ id, message }: FieldErrorProps) {
  if (!message) {
    return null
  }
  return (
    <p className="field-error" id={id}>
      {message}
    </p>
  )
}
