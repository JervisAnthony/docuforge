import type { ToolDefinition } from '../tools/types'
import { ToolCard } from './ToolCard'

interface ToolSectionProps {
  title: string
  description: string
  tools: readonly ToolDefinition[]
}

export function ToolSection({ title, description, tools }: ToolSectionProps) {
  const headingId = `${title.toLowerCase().replace(/\s+/g, '-')}-heading`

  return (
    <section className="tool-section" aria-labelledby={headingId}>
      <div className="tool-section__heading">
        <div>
          <p className="eyebrow">{title === 'PDF tools' ? 'Documents' : 'Pictures'}</p>
          <h2 id={headingId}>{title}</h2>
        </div>
        <p>{description}</p>
      </div>
      <div className="tool-grid">
        {tools.map((tool) => (
          <ToolCard key={tool.id} tool={tool} />
        ))}
      </div>
    </section>
  )
}
