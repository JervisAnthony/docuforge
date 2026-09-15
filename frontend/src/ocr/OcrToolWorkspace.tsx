import { useEffect, useRef } from 'react'
import { toolById } from '../tools/catalog'
import type { OcrToolId } from '../tools/types'
import type { MultipartRequestClient } from '../workflows/useSubmission'
import { OcrSearchablePdfForm } from './OcrSearchablePdfForm'
import { OcrTextForm } from './OcrTextForm'

interface OcrToolWorkspaceProps {
  toolId: OcrToolId
  onBack: () => void
  client?: MultipartRequestClient
}

export function OcrToolWorkspace({ toolId, onBack, client }: OcrToolWorkspaceProps) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  const tool = toolById(toolId)

  useEffect(() => {
    headingRef.current?.focus()
  }, [toolId])

  return (
    <section className="workflow-workspace" aria-labelledby="workflow-heading">
      <button type="button" className="button button--back" onClick={onBack}>
        ← Back to tools
      </button>
      <div className="workflow-heading">
        <p className="eyebrow">OCR workspace</p>
        <h1 id="workflow-heading" ref={headingRef} tabIndex={-1}>{tool.title}</h1>
        <p>{tool.description}</p>
        <p>OCR requires the server OCR engine to be available.</p>
      </div>
      <div className="workflow-panel">
        {toolId === 'ocr-pdf-to-searchable-pdf' ? (
          <OcrSearchablePdfForm client={client} />
        ) : (
          <OcrTextForm toolId={toolId} client={client} />
        )}
      </div>
    </section>
  )
}
