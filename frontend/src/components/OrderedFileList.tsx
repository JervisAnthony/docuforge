import { formatFileSize } from '../utils/files'

interface OrderedFileListProps {
  files: readonly File[]
  heading: string
  headingId: string
  onFiles: (files: File[]) => void
  disabled?: boolean
}

export function OrderedFileList({
  files,
  heading,
  headingId,
  onFiles,
  disabled = false,
}: OrderedFileListProps) {
  function moveFile(index: number, direction: -1 | 1) {
    const nextFiles = [...files]
    const target = index + direction
    ;[nextFiles[index], nextFiles[target]] = [nextFiles[target], nextFiles[index]]
    onFiles(nextFiles)
  }

  if (!files.length) {
    return null
  }

  return (
    <div className="selected-files" aria-labelledby={headingId}>
      <div className="selected-files__header">
        <h2 id={headingId}>{heading}</h2>
        <button
          type="button"
          className="button button--quiet"
          onClick={() => onFiles([])}
          disabled={disabled}
        >
          Clear all
        </button>
      </div>
      <ol>
        {files.map((file, index) => (
          <li key={`${file.name}-${file.size}-${file.lastModified}-${index}`}>
            <div className="selected-files__name">
              <strong>{file.name}</strong>
              <span>{formatFileSize(file.size)}</span>
            </div>
            <div className="selected-files__actions">
              <button
                type="button"
                className="button button--quiet"
                aria-label={`Move ${file.name} up`}
                disabled={index === 0 || disabled}
                onClick={() => moveFile(index, -1)}
              >
                Move up
              </button>
              <button
                type="button"
                className="button button--quiet"
                aria-label={`Move ${file.name} down`}
                disabled={index === files.length - 1 || disabled}
                onClick={() => moveFile(index, 1)}
              >
                Move down
              </button>
              <button
                type="button"
                className="button button--quiet button--danger"
                aria-label={`Remove ${file.name}`}
                disabled={disabled}
                onClick={() => onFiles(files.filter((_, itemIndex) => itemIndex !== index))}
              >
                Remove
              </button>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
