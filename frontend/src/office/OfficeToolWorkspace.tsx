import { useEffect, useRef } from 'react'
import { toolById } from '../tools/catalog'
import type { OfficeToolId } from '../tools/types'
import type { MultipartRequestClient } from '../workflows/useSubmission'
import { OfficeToPdfForm } from './OfficeToPdfForm'

interface OfficeToolWorkspaceProps {
  toolId: OfficeToolId
  onBack: () => void
  client?: MultipartRequestClient
}

export function OfficeToolWorkspace({ toolId, onBack, client }: OfficeToolWorkspaceProps) {
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
        <p className="eyebrow">Office workspace</p>
        <h1 id="workflow-heading" ref={headingRef} tabIndex={-1}>
          {tool.title}
        </h1>
        <p>{tool.description}</p>
      </div>
      <div className="workflow-panel">
        <OfficeToPdfForm toolId={toolId} client={client} />
      </div>
    </section>
  )
}
