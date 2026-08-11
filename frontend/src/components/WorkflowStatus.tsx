import type { WorkflowFeedback } from '../workflows/useSubmission'

interface WorkflowStatusProps {
  feedback: WorkflowFeedback
}

export function WorkflowStatus({ feedback }: WorkflowStatusProps) {
  if (feedback.status === 'idle') {
    return null
  }
  if (feedback.status === 'error') {
    return (
      <div className="workflow-feedback workflow-feedback--error" role="alert">
        {feedback.message}
      </div>
    )
  }

  const message =
    feedback.status === 'ready'
      ? 'Ready to process.'
      : feedback.status === 'submitting'
        ? 'Processing…'
        : `Complete. Downloaded ${feedback.filename}.`

  return (
    <div
      className={`workflow-feedback workflow-feedback--${feedback.status}`}
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {feedback.status === 'submitting' ? (
        <span className="processing-spinner" aria-hidden="true" />
      ) : null}
      {message}
    </div>
  )
}
