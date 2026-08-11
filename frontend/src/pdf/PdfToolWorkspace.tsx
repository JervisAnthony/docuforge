import { useEffect, useRef } from 'react'
import { toolById } from '../tools/catalog'
import type { PdfToolId } from '../tools/types'
import { ExtractPagesPdfForm } from './ExtractPagesPdfForm'
import { MergePdfForm } from './MergePdfForm'
import { PdfToImagesForm } from './PdfToImagesForm'
import { RemovePagesPdfForm } from './RemovePagesPdfForm'
import { RotatePdfForm } from './RotatePdfForm'
import { SplitPdfForm } from './SplitPdfForm'
import type { PdfRequestClient } from './types'

interface PdfToolWorkspaceProps {
  toolId: PdfToolId
  onBack: () => void
  client?: PdfRequestClient
}

export function PdfToolWorkspace({ toolId, onBack, client }: PdfToolWorkspaceProps) {
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
        <p className="eyebrow">PDF workspace</p>
        <h1 id="workflow-heading" ref={headingRef} tabIndex={-1}>
          {tool.title}
        </h1>
        <p>{tool.description}</p>
      </div>
      <div className="workflow-panel">{renderForm(toolId, client)}</div>
    </section>
  )
}

function renderForm(toolId: PdfToolId, client?: PdfRequestClient) {
  switch (toolId) {
    case 'pdf-merge':
      return <MergePdfForm client={client} />
    case 'pdf-split':
      return <SplitPdfForm client={client} />
    case 'pdf-rotate':
      return <RotatePdfForm client={client} />
    case 'pdf-remove-pages':
      return <RemovePagesPdfForm client={client} />
    case 'pdf-extract-pages':
      return <ExtractPagesPdfForm client={client} />
    case 'pdf-to-images':
      return <PdfToImagesForm client={client} />
  }
}
