import { useEffect, useRef, useState } from 'react'
import { apiClient, ApiClientError } from '../api/client'
import type { ApiClient } from '../api/client'
import type { BatchSnapshot } from '../api/types'
import { FieldError } from '../components/FieldError'
import { FilePicker } from '../components/FilePicker'
import { OrderedFileList } from '../components/OrderedFileList'
import { IMAGE_FORMAT_SUFFIX, RASTER_IMAGE_ACCEPT, isRasterImageFile } from '../image/formats'
import type { ImageFormat } from '../image/formats'
import { parseKilobytesToBytes, parsePositiveInteger } from '../image/integer'
import type { CompressionMode } from '../image/types'
import { toolById } from '../tools/catalog'
import type { BatchToolId } from '../tools/types'
import { downloadBlob, filenameFromContentDisposition } from '../utils/download'

interface BatchToolWorkspaceProps {
  toolId: BatchToolId
  onBack: () => void
  client?: ApiClient
}

const OFFICE_ACCEPT = '.docx,.pptx,.xlsx'
const POLL_INTERVAL_MS = 800

export function BatchToolWorkspace({ toolId, onBack, client = apiClient }: BatchToolWorkspaceProps) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  const inFlightRef = useRef(false)
  const mountedRef = useRef(true)
  const pollTimerRef = useRef<number | null>(null)
  const accessTokenRef = useRef<string | null>(null)
  const tool = toolById(toolId)
  const [files, setFiles] = useState<File[]>([])
  const [format, setFormat] = useState<ImageFormat>('jpeg')
  const [maxWidth, setMaxWidth] = useState('1200')
  const [maxHeight, setMaxHeight] = useState('')
  const [allowUpscale, setAllowUpscale] = useState(false)
  const [compressionMode, setCompressionMode] = useState<CompressionMode>('quality')
  const [quality, setQuality] = useState('80')
  const [targetKilobytes, setTargetKilobytes] = useState('')
  const [snapshot, setSnapshot] = useState<BatchSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [pollRevision, setPollRevision] = useState(0)

  useEffect(() => headingRef.current?.focus(), [toolId])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (!snapshot || !accessTokenRef.current || snapshot.phase === 'ready' || snapshot.phase === 'error' || error) return
    let active = true
    pollTimerRef.current = window.setTimeout(async () => {
      pollTimerRef.current = null
      if (inFlightRef.current) return
      inFlightRef.current = true
      if (mountedRef.current) setBusy(true)
      try {
        const next = await client.getBatchStatus(snapshot.id, accessTokenRef.current as string)
        if (active) setSnapshot(next)
      } catch (caught: unknown) {
        if (active) setError(errorMessage(caught, 'Status could not be refreshed.'))
      } finally {
        inFlightRef.current = false
        if (mountedRef.current) {
          setBusy(false)
          setPollRevision((revision) => revision + 1)
        }
      }
    }, POLL_INTERVAL_MS)
    return () => {
      active = false
      if (pollTimerRef.current !== null) {
        window.clearTimeout(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [client, error, pollRevision, snapshot])

  const active = Boolean(snapshot && snapshot.phase !== 'ready' && snapshot.phase !== 'error')
  const isOffice = toolId === 'batch-office-to-pdf'
  const invalidFiles = files.some((file) => isOffice ? !isOfficeFile(file) : !isRasterImageFile(file))
  const widthError = optionalPositiveIntegerError(maxWidth, 'Maximum width')
  const heightError = optionalPositiveIntegerError(maxHeight, 'Maximum height')
  const resizeError = toolId === 'batch-image-resize' && !maxWidth && !maxHeight
    ? 'Enter a maximum width or height.'
    : null
  const qualityError = compressionMode === 'quality' ? validateQuality(quality) : null
  const targetSizeError = compressionMode === 'max-size' ? validateTargetKilobytes(targetKilobytes) : null
  const compressionFormatError = toolId === 'batch-image-compress' && compressionMode === 'quality' && format !== 'jpeg' && format !== 'webp'
    ? 'Quality compression is available for JPEG and WebP.'
    : null
  const valid = files.length > 0 && !invalidFiles && !widthError && !heightError && !resizeError && !qualityError && !targetSizeError && !compressionFormatError

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!valid || active || !beginRequest()) return
    const data = new FormData()
    files.forEach((file) => data.append('file', file))
    if (!isOffice) data.append('format', format)
    if (toolId === 'batch-image-resize') {
      if (maxWidth) data.append('max_width', maxWidth)
      if (maxHeight) data.append('max_height', maxHeight)
      data.append('allow_upscale', allowUpscale ? 'true' : 'false')
    }
    if (toolId === 'batch-image-compress') {
      if (compressionMode === 'quality') {
        data.append('quality', quality)
      } else {
        const maxBytes = parseKilobytesToBytes(targetKilobytes)
        if (maxBytes === null) return
        data.append('max_bytes', String(maxBytes))
      }
    }
    setError(null)
    try {
      const handle = await client.createBatch(tool.endpoint, data)
      accessTokenRef.current = handle.accessToken
      setSnapshot(handle.snapshot)
    } catch (caught: unknown) {
      setError(errorMessage(caught, 'The batch could not be started.'))
    } finally {
      endRequest()
    }
  }

  async function update(action: 'cancel' | 'recover' | 'status') {
    const accessToken = accessTokenRef.current
    if (!snapshot || !accessToken || !beginRequest()) return
    setError(null)
    try {
      const next = action === 'cancel'
        ? await client.cancelBatch(snapshot.id, accessToken)
        : action === 'recover'
          ? await client.recoverBatch(snapshot.id, accessToken)
          : await client.getBatchStatus(snapshot.id, accessToken)
      setSnapshot(next)
    } catch (caught: unknown) {
      setError(errorMessage(caught, 'The batch request could not be completed.'))
    } finally {
      endRequest()
    }
  }

  async function download() {
    const accessToken = accessTokenRef.current
    if (!snapshot?.can_download || !accessToken || !beginRequest()) return
    setError(null)
    try {
      const response = await client.downloadBatch(snapshot.id, accessToken)
      downloadBlob(
        response.blob,
        filenameFromContentDisposition(response.contentDisposition, `docuforge-batch-${snapshot.id}.zip`),
      )
    } catch (caught: unknown) {
      setError(errorMessage(caught, 'The ZIP could not be downloaded.'))
    } finally {
      endRequest()
    }
  }

  function beginRequest(): boolean {
    if (inFlightRef.current) return false
    clearScheduledPoll()
    inFlightRef.current = true
    if (mountedRef.current) setBusy(true)
    return true
  }

  function endRequest() {
    inFlightRef.current = false
    if (mountedRef.current) {
      setBusy(false)
      setPollRevision((revision) => revision + 1)
    }
  }

  function clearScheduledPoll() {
    if (pollTimerRef.current === null) return
    window.clearTimeout(pollTimerRef.current)
    pollTimerRef.current = null
  }

  return (
    <section className="workflow-workspace" aria-labelledby="workflow-heading">
      <button type="button" className="button button--back" onClick={onBack}>← Back to tools</button>
      <div className="workflow-heading">
        <p className="eyebrow">Batch workspace</p>
        <h1 id="workflow-heading" ref={headingRef} tabIndex={-1}>{tool.title}</h1>
        <p>{tool.description}</p>
      </div>
      <div className="workflow-panel">
        <form className="workflow-form" aria-label={`${tool.title} form`} onSubmit={submit} noValidate>
          <FilePicker
            id={`${toolId}-files`}
            label={isOffice ? 'Office files' : 'Image files'}
            files={files}
            onFiles={(next) => { setFiles(next); setError(null) }}
            multiple
            disabled={busy || active}
            accept={isOffice ? OFFICE_ACCEPT : RASTER_IMAGE_ACCEPT}
            helpText="Input order is preserved in the batch and ZIP."
          />
          <FieldError id="batch-files-error" message={invalidFiles ? (isOffice ? 'Choose DOCX, PPTX, or XLSX files.' : 'Choose supported image files.') : null} />
          <OrderedFileList files={files} heading="Selected files" headingId="batch-selected-files" onFiles={setFiles} disabled={busy || active} />
          {!isOffice ? (
            <div className="form-field">
              <label htmlFor="batch-format">Output format</label>
              <select id="batch-format" value={format} disabled={busy || active} onChange={(event) => setFormat(event.target.value as ImageFormat)}>
                {Object.keys(IMAGE_FORMAT_SUFFIX).map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}
              </select>
            </div>
          ) : null}
          {toolId === 'batch-image-resize' ? (
            <>
              <div className="form-field-row">
                <NumberField id="batch-max-width" label="Maximum width" value={maxWidth} disabled={busy || active} onChange={setMaxWidth} error={widthError} />
                <NumberField id="batch-max-height" label="Maximum height" value={maxHeight} disabled={busy || active} onChange={setMaxHeight} error={heightError} />
              </div>
              <FieldError id="batch-resize-error" message={resizeError} />
              <label className="checkbox-control" htmlFor="batch-allow-upscale"><input id="batch-allow-upscale" type="checkbox" checked={allowUpscale} disabled={busy || active} onChange={(event) => setAllowUpscale(event.currentTarget.checked)} /><span>Allow upscaling<small>Off by default.</small></span></label>
            </>
          ) : null}
          {toolId === 'batch-image-compress' ? (
            <>
              <fieldset className="choice-fieldset"><legend>Compression mode</legend><div className="choice-options"><label><input type="radio" name="batch-compression-mode" checked={compressionMode === 'quality'} disabled={busy || active} onChange={() => setCompressionMode('quality')} />Quality</label><label><input type="radio" name="batch-compression-mode" checked={compressionMode === 'max-size'} disabled={busy || active} onChange={() => setCompressionMode('max-size')} />Maximum file size</label></div></fieldset>
              {compressionMode === 'quality'
                ? <NumberField id="batch-quality" label="Quality" value={quality} disabled={busy || active} onChange={setQuality} error={qualityError ?? compressionFormatError} max="95" />
                : <NumberField id="batch-target-kb" label="Maximum size (KB)" value={targetKilobytes} disabled={busy || active} onChange={setTargetKilobytes} error={targetSizeError} />}
            </>
          ) : null}
          {!snapshot ? (
            <div className="workflow-actions"><button className="button button--primary" type="submit" disabled={!valid || busy}>{busy ? 'Starting…' : 'Start batch'}</button></div>
          ) : <BatchStatusView snapshot={snapshot} busy={busy} onCancel={() => void update('cancel')} onRecover={() => void update('recover')} onDownload={() => void download()} />}
          {error ? <div className="workflow-feedback workflow-feedback--error" role="alert"><span>{error}</span>{snapshot ? <button className="button button--secondary" type="button" disabled={busy} onClick={() => void update('status')}>Retry status</button> : null}</div> : null}
        </form>
      </div>
    </section>
  )
}

function NumberField({ id, label, value, disabled, onChange, error, max }: { id: string; label: string; value: string; disabled: boolean; onChange: (value: string) => void; error?: string | null; max?: string }) {
  return <div className="form-field"><label htmlFor={id}>{label}</label><input id={id} type="number" min="1" max={max} step="1" value={value} disabled={disabled} aria-invalid={error ? 'true' : undefined} aria-describedby={error ? `${id}-error` : undefined} onChange={(event) => onChange(event.target.value)} /><FieldError id={`${id}-error`} message={error ?? null} /></div>
}

function BatchStatusView({ snapshot, busy, onCancel, onRecover, onDownload }: { snapshot: BatchSnapshot; busy: boolean; onCancel: () => void; onRecover: () => void; onDownload: () => void }) {
  const { summary } = snapshot
  return (
    <section className="batch-status" aria-label="Batch status">
      <div className="batch-progress">
        <p className="batch-progress__label"><strong>{snapshot.progress_percent}%</strong><span>{summary.processed} / {summary.total} processed</span></p>
        <progress max="100" value={snapshot.progress_percent}>{snapshot.progress_percent}%</progress>
      </div>
      <p className="batch-summary"><span>Status: {snapshot.status}</span><span>Completed: {summary.completed}</span><span>Failed: {summary.failed}</span><span>Cancelled: {summary.cancelled}</span><span>Attempt: {snapshot.attempt}</span></p>
      {snapshot.cancellation_requested ? <p className="workflow-feedback">Cancellation requested. The file currently being processed may finish before the remaining files stop.</p> : null}
      {snapshot.session_error ? <p className="workflow-feedback workflow-feedback--error" role="alert">{snapshot.session_error.message}</p> : null}
      <ol className="batch-items" aria-label="Batch items">
        {snapshot.items.map((item) => <li className="batch-item" key={item.id}><span className="batch-item__position">{item.position + 1}</span><span className="batch-item__details"><strong>{item.descriptor}</strong>{item.result_descriptor ? <small>{item.result_descriptor}</small> : null}{item.failure ? <small>{item.failure.message}</small> : null}</span><span className="batch-item__state">{item.status}</span></li>)}
      </ol>
      <div className="workflow-actions">
        {snapshot.can_cancel ? <button className="button button--danger" type="button" disabled={busy} onClick={onCancel}>Cancel</button> : null}
        {snapshot.can_recover ? <button className="button button--secondary" type="button" disabled={busy} onClick={onRecover}>{recoveryLabel(snapshot)}</button> : null}
        {snapshot.can_download ? <button className="button button--primary" type="button" disabled={busy} onClick={onDownload}>Download ZIP</button> : null}
      </div>
    </section>
  )
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiClientError ? error.message : fallback
}

function recoveryLabel(snapshot: BatchSnapshot): string {
  if (['batch_packaging_failed', 'batch_packaging_interrupted'].includes(snapshot.session_error?.code ?? '')) return 'Retry packaging'
  if (['batch_execution_failed', 'batch_execution_interrupted'].includes(snapshot.session_error?.code ?? '')) return 'Retry batch'
  return 'Retry failed/cancelled items'
}

function optionalPositiveIntegerError(value: string, label: string): string | null {
  return value && parsePositiveInteger(value) === null ? `${label} must be a positive whole number.` : null
}

function validateQuality(value: string): string | null {
  const parsed = parsePositiveInteger(value)
  return parsed !== null && parsed <= 95 ? null : 'Quality must be a whole number from 1 through 95.'
}

function validateTargetKilobytes(value: string): string | null {
  return parseKilobytesToBytes(value) === null ? 'Maximum size must be a positive whole number of KB within the safe range.' : null
}

function isOfficeFile(file: File): boolean {
  return /\.(docx|pptx|xlsx)$/i.test(file.name)
}
