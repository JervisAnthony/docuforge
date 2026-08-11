import type { ToolDefinition } from '../tools/types'

interface ToolCardProps {
  tool: ToolDefinition
}

export function ToolCard({ tool }: ToolCardProps) {
  return (
    <article className="tool-card">
      <div className={`tool-card__icon tool-card__icon--${tool.category}`} aria-hidden="true">
        {tool.category === 'pdf' ? 'P' : 'I'}
      </div>
      <div className="tool-card__content">
        <h3>{tool.title}</h3>
        <p>{tool.description}</p>
      </div>
      <p className="tool-card__status">
        <span aria-hidden="true">●</span> Backend ready · Interface coming next
      </p>
    </article>
  )
}
