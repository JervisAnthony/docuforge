import { useEffect, useRef } from 'react'
import { toolById } from '../tools/catalog'
import type { ImageToolId } from '../tools/types'
import { CompressImageForm } from './CompressImageForm'
import { ConvertImageForm } from './ConvertImageForm'
import { ImagesToPdfForm } from './ImagesToPdfForm'
import { ResizeImageForm } from './ResizeImageForm'
import type { ImageRequestClient } from './types'

interface ImageToolWorkspaceProps {
  toolId: ImageToolId
  onBack: () => void
  client?: ImageRequestClient
}

export function ImageToolWorkspace({ toolId, onBack, client }: ImageToolWorkspaceProps) {
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
        <p className="eyebrow">Image workspace</p>
        <h1 id="workflow-heading" ref={headingRef} tabIndex={-1}>
          {tool.title}
        </h1>
        <p>{tool.description}</p>
      </div>
      <div className="workflow-panel">{renderForm(toolId, client)}</div>
    </section>
  )
}

function renderForm(toolId: ImageToolId, client?: ImageRequestClient) {
  switch (toolId) {
    case 'image-convert':
      return <ConvertImageForm client={client} />
    case 'image-resize':
      return <ResizeImageForm client={client} />
    case 'image-compress':
      return <CompressImageForm client={client} />
    case 'images-to-pdf':
      return <ImagesToPdfForm client={client} />
  }
}
