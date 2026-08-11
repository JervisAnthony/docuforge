import type { ToolDefinition, ToolId } from '../tools/types'

interface ToolCardProps {
  tool: ToolDefinition
  onOpen?: (toolId: ToolId) => void
}

export function ToolCard({ tool, onOpen }: ToolCardProps) {
  const operational = tool.interfaceStatus === 'operational'
  return (
    <article className="tool-card">
      <div className={`tool-card__icon tool-card__icon--${tool.category}`} aria-hidden="true">
        {tool.category === 'pdf' ? 'P' : 'I'}
      </div>
      <div className="tool-card__content">
        <h3>{tool.title}</h3>
        <p>{tool.description}</p>
      </div>
      {operational ? (
        <div className="tool-card__action">
          <p className="tool-card__status tool-card__status--ready">
            <span aria-hidden="true">●</span> Ready
          </p>
          <button
            type="button"
            className="button button--secondary"
            aria-label={`Open ${tool.title}`}
            onClick={() => onOpen?.(tool.id)}
          >
            Open tool
          </button>
        </div>
      ) : (
        <p className="tool-card__status">
          <span aria-hidden="true">●</span> Backend available · Browser workflow unavailable
        </p>
      )}
    </article>
  )
}
