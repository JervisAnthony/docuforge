import { formatFileSize } from '../utils/files'

interface SelectedFileProps {
  file: File
  onClear: () => void
  disabled?: boolean
}

export function SelectedFile({ file, onClear, disabled = false }: SelectedFileProps) {
  return (
    <div className="selected-file">
      <div>
        <strong>{file.name}</strong>
        <span>{formatFileSize(file.size)}</span>
      </div>
      <button type="button" className="button button--quiet" onClick={onClear} disabled={disabled}>
        Clear file
      </button>
    </div>
  )
}
