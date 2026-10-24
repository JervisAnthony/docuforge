import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient, ApiClientError } from '../api/client'
import type { ApiClient } from '../api/client'
import type { BatchSnapshot, BatchSessionHandle } from '../api/types'
import { decodeRecoveryKey, encodeRecoveryKey } from './recoveryKey'
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
  session?: BatchSessionHandle
  onSessionChange: (toolId: BatchToolId, handle: BatchSessionHandle) => void
  onSessionClear: (toolId: BatchToolId, batchId: string) => void
  onBack: () => void
  client?: ApiClient
}

const OFFICE_ACCEPT = '.docx,.pptx,.xlsx'
const POLL_INTERVAL_MS = 800

export function BatchToolWorkspace({ toolId, session, onSessionChange, onSessionClear, onBack, client = apiClient }: BatchToolWorkspaceProps) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  const inFlightRef = useRef(false)
  const mountedRef = useRef(true)
  const pollTimerRef = useRef<number | null>(null)
  const generationRef = useRef(0)
  const resumeGenerationRef = useRef(0)
  const [verified, setVerified] = useState(false)
  const [creating, setCreating] = useState(false)
  const [resumeOpen, setResumeOpen] = useState(false)
  const [recoveryKey, setRecoveryKey] = useState('')
  const snapshot = session?.snapshot ?? null
  const tool = toolById(toolId)
  const [files, setFiles] = useState<File[]>([])
  const [format, setFormat] = useState<ImageFormat>('jpeg')
  const [maxWidth, setMaxWidth] = useState('1200')
  const [maxHeight, setMaxHeight] = useState('')
  const [allowUpscale, setAllowUpscale] = useState(false)
  const [compressionMode, setCompressionMode] = useState<CompressionMode>('quality')
  const [quality, setQuality] = useState('80')
  const [targetKilobytes, setTargetKilobytes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [deleteConfirmation, setDeleteConfirmation] = useState(false)
  const [success, setSuccess] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [pollRevision, setPollRevision] = useState(0)

  const clearScheduledPoll = useCallback(() => {
    if (pollTimerRef.current === null) return
    window.clearTimeout(pollTimerRef.current)
    pollTimerRef.current = null
  }, [])

  const beginRequest = useCallback((): boolean => {
    if (inFlightRef.current) return false
    clearScheduledPoll()
    inFlightRef.current = true
    if (mountedRef.current) setBusy(true)
    return true
  }, [clearScheduledPoll])

  const endRequest = useCallback(() => {
    inFlightRef.current = false
    if (mountedRef.current) {
      setBusy(false)
      setPollRevision((revision) => revision + 1)
    }
  }, [])

  useEffect(() => headingRef.current?.focus(), [toolId])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      generationRef.current += 1
      mountedRef.current = false
      clearScheduledPoll()
    }
  }, [clearScheduledPoll])

  useEffect(() => {
    if (inFlightRef.current) return
    if (!session || error || (verified && ['ready', 'error'].includes(session.snapshot.phase))) return
    let current = true
    pollTimerRef.current = window.setTimeout(async () => {
      pollTimerRef.current = null
      if (!beginRequest()) return
      try {
        const next = await client.getBatchStatus(session.snapshot.id, session.accessToken)
        if (!current) return
        validateSnapshot(next, session.snapshot.id, toolId)
        onSessionChange(toolId, { ...session, snapshot: next })
        setVerified(true)
      } catch (caught: unknown) {
        if (current) {
          if (isUnavailable(caught)) {
            onSessionClear(toolId, session.snapshot.id)
            setVerified(false)
            setSuccess('This batch is no longer available. It may have expired or been deleted.')
          } else {
            setError('Could not reconnect to this batch. Retry status.')
          }
        }
      } finally {
        endRequest()
      }
    }, verified ? POLL_INTERVAL_MS : 0)
    return () => {
      current = false
      clearScheduledPoll()
    }
  }, [client, error, pollRevision, session, toolId, verified, onSessionChange, onSessionClear, beginRequest, endRequest, clearScheduledPoll])

  async function resume(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const credential = decodeRecoveryKey(recoveryKey)
    if (!credential) { setError('Enter a valid DocuForge recovery key.'); return }
    if (session || !beginRequest()) return
    const generation = generationRef.current
    const attempt = ++resumeGenerationRef.current
    setError(null)
    try {
      const next = await client.getBatchStatus(credential.batchId, credential.accessToken)
      if (!mountedRef.current || generation !== generationRef.current || attempt !== resumeGenerationRef.current) return
      validateSnapshot(next, credential.batchId, toolId)
      setVerified(true)
      onSessionChange(toolId, { snapshot: next, accessToken: credential.accessToken })
      setRecoveryKey('')
      setResumeOpen(false)
    } catch (caught: unknown) {
      if (mountedRef.current && generation === generationRef.current && attempt === resumeGenerationRef.current) {
        setError(caught instanceof OperationMismatch ? caught.message : isUnavailable(caught)
          ? 'This batch is unavailable or the recovery key is invalid.'
          : 'Could not reach DocuForge. Retry with the same recovery key.')
      }
    } finally { endRequest() }
  }

  async function copyRecoveryKey() {
    if (!session || !beginRequest()) return
    setSuccess(null)
    setError(null)
    const generation = generationRef.current
    try {
      await navigator.clipboard.writeText(encodeRecoveryKey(session))
      if (mountedRef.current && generation === generationRef.current) setSuccess('Recovery key copied. Keep it private.')
    } catch {
      if (mountedRef.current && generation === generationRef.current) setError('Could not copy the recovery key. Try again.')
    } finally { endRequest() }
  }

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
    if (!valid || session || !beginRequest()) return
    setCreating(true)
    const generation = generationRef.current
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
    setSuccess(null)
    setDeleteConfirmation(false)
    try {
      const handle = await client.createBatch(tool.endpoint, data)
      if (!mountedRef.current || generation !== generationRef.current) return
      setVerified(true)
      onSessionChange(toolId, handle)
    } catch {
      if (mountedRef.current && generation === generationRef.current) setError('The batch could not be started.')
    } finally {
      if (mountedRef.current) setCreating(false)
      endRequest()
    }
  }

  async function update(action: 'cancel' | 'recover' | 'status') {
    const accessToken = session?.accessToken
    if (!snapshot || !accessToken || !beginRequest()) return
    if (!verified && action !== 'status') { endRequest(); return }
    const generation = generationRef.current
    setError(null)
    try {
      const next = action === 'cancel'
        ? await client.cancelBatch(snapshot.id, accessToken)
        : action === 'recover'
          ? await client.recoverBatch(snapshot.id, accessToken)
          : await client.getBatchStatus(snapshot.id, accessToken)
      if (!mountedRef.current || generation !== generationRef.current) return
      validateSnapshot(next, snapshot.id, toolId)
      onSessionChange(toolId, { snapshot: next, accessToken })
      setVerified(true)
    } catch (caught: unknown) {
      if (mountedRef.current && generation === generationRef.current) {
        if (isUnavailable(caught)) {
          onSessionClear(toolId, snapshot.id)
          setVerified(false)
          setSuccess('This batch is no longer available. It may have expired or been deleted.')
        } else setError('Could not reconnect to this batch. Retry status.')
      }
    } finally {
      endRequest()
    }
  }

  async function download() {
    const accessToken = session?.accessToken
    if (!verified || !snapshot?.can_download || !accessToken || !beginRequest()) return
    const generation = generationRef.current
    setError(null)
    try {
      const response = await client.downloadBatch(snapshot.id, accessToken)
      if (!mountedRef.current || generation !== generationRef.current) return
      downloadBlob(
        response.blob,
        filenameFromContentDisposition(response.contentDisposition, `docuforge-batch-${snapshot.id}.zip`),
      )
    } catch {
      if (mountedRef.current && generation === generationRef.current) setError('The ZIP could not be downloaded.')
    } finally {
      endRequest()
    }
  }

  async function deleteBatch() {
    const accessToken = session?.accessToken
    if (!snapshot || !accessToken || !beginRequest()) return
    if (!verified) { endRequest(); return }
    const generation = generationRef.current
    setError(null)
    try {
      await client.deleteBatch(snapshot.id, accessToken)
      if (!mountedRef.current || generation !== generationRef.current) return
      onSessionClear(toolId, snapshot.id)
      setVerified(false)
      setRecoveryKey('')
      setResumeOpen(false)
      setFiles([])
      setDeleteConfirmation(false)
      setSuccess('Batch deleted from the server.')
    } catch {
      if (mountedRef.current && generation === generationRef.current) setError('The batch could not be deleted. Retry the deletion.')
    } finally {
      endRequest()
    }
  }


  return (
    <section className="workflow-workspace" aria-labelledby="workflow-heading">
      <button type="button" className="button button--back" onClick={onBack} disabled={creating}>← Back to tools</button>
      <div className="workflow-heading">
        <p className="eyebrow">Batch workspace</p>
        <h1 id="workflow-heading" ref={headingRef} tabIndex={-1}>{tool.title}</h1>
        <p>{tool.description}</p>
      </div>
      <div className="workflow-panel">
        {!session ? <>
          <button type="button" className="button button--secondary" disabled={busy} onClick={() => { setResumeOpen(true); setError(null) }}>Resume a batch</button>
          {resumeOpen ? <form aria-label="Resume a batch" onSubmit={resume}>
            <label htmlFor="batch-recovery-key">Recovery key</label>
            <input id="batch-recovery-key" type="password" autoComplete="off" spellCheck={false} value={recoveryKey} disabled={busy} onChange={(event) => setRecoveryKey(event.target.value)} />
            <button type="submit" disabled={busy}>Resume</button>
            <button type="button" onClick={() => { resumeGenerationRef.current += 1; setRecoveryKey(''); setResumeOpen(false); setError(null) }}>Dismiss resume</button>
          </form> : null}
        </> : <>
          {!verified ? <p role="status">Reconnecting to batch...</p> : null}
          <button type="button" className="button button--secondary" disabled={busy || !verified} onClick={() => void copyRecoveryKey()}>Copy recovery key</button>
          <p>Anyone with this key can access this batch until it expires or is deleted. Keep it private.</p>
        </>}
        <form className="workflow-form" aria-label={`${tool.title} form`} onSubmit={submit} noValidate>
          <FilePicker
            id={`${toolId}-files`}
            label={isOffice ? 'Office files' : 'Image files'}
            files={files}
            onFiles={(next) => { setFiles(next); setError(null) }}
            multiple
            disabled={busy || Boolean(session)}
            accept={isOffice ? OFFICE_ACCEPT : RASTER_IMAGE_ACCEPT}
            helpText="Input order is preserved in the batch and ZIP."
          />
          <FieldError id="batch-files-error" message={invalidFiles ? (isOffice ? 'Choose DOCX, PPTX, or XLSX files.' : 'Choose supported image files.') : null} />
          <OrderedFileList files={files} heading="Selected files" headingId="batch-selected-files" onFiles={setFiles} disabled={busy || Boolean(session)} />
          {!isOffice ? (
            <div className="form-field">
              <label htmlFor="batch-format">Output format</label>
              <select id="batch-format" value={format} disabled={busy || Boolean(session)} onChange={(event) => setFormat(event.target.value as ImageFormat)}>
                {Object.keys(IMAGE_FORMAT_SUFFIX).map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}
              </select>
            </div>
          ) : null}
          {toolId === 'batch-image-resize' ? (
            <>
              <div className="form-field-row">
                <NumberField id="batch-max-width" label="Maximum width" value={maxWidth} disabled={busy || Boolean(session)} onChange={setMaxWidth} error={widthError} />
                <NumberField id="batch-max-height" label="Maximum height" value={maxHeight} disabled={busy || Boolean(session)} onChange={setMaxHeight} error={heightError} />
              </div>
              <FieldError id="batch-resize-error" message={resizeError} />
              <label className="checkbox-control" htmlFor="batch-allow-upscale"><input id="batch-allow-upscale" type="checkbox" checked={allowUpscale} disabled={busy || Boolean(session)} onChange={(event) => setAllowUpscale(event.currentTarget.checked)} /><span>Allow upscaling<small>Off by default.</small></span></label>
            </>
          ) : null}
          {toolId === 'batch-image-compress' ? (
            <>
              <fieldset className="choice-fieldset"><legend>Compression mode</legend><div className="choice-options"><label><input type="radio" name="batch-compression-mode" checked={compressionMode === 'quality'} disabled={busy || Boolean(session)} onChange={() => setCompressionMode('quality')} />Quality</label><label><input type="radio" name="batch-compression-mode" checked={compressionMode === 'max-size'} disabled={busy || Boolean(session)} onChange={() => setCompressionMode('max-size')} />Maximum file size</label></div></fieldset>
              {compressionMode === 'quality'
                ? <NumberField id="batch-quality" label="Quality" value={quality} disabled={busy || Boolean(session)} onChange={setQuality} error={qualityError ?? compressionFormatError} max="95" />
                : <NumberField id="batch-target-kb" label="Maximum size (KB)" value={targetKilobytes} disabled={busy || Boolean(session)} onChange={setTargetKilobytes} error={targetSizeError} />}
            </>
          ) : null}
          {!snapshot ? (
            <div className="workflow-actions"><button className="button button--primary" type="submit" disabled={!valid || busy || resumeOpen}>{busy ? 'Starting…' : 'Start batch'}</button></div>
          ) : <BatchStatusView snapshot={snapshot} busy={busy || !verified} onCancel={() => void update('cancel')} onRecover={() => void update('recover')} onDownload={() => void download()} onDelete={() => setDeleteConfirmation(true)} />}
          {deleteConfirmation && snapshot ? (
            <div className="workflow-feedback" role="group" aria-label="Confirm batch deletion">
              <p>Delete this batch and its retained files? This cannot be undone.</p>
              <div className="workflow-actions">
                <button className="button button--danger" type="button" disabled={busy} onClick={() => void deleteBatch()}>Delete now</button>
                <button className="button button--secondary" type="button" disabled={busy} onClick={() => setDeleteConfirmation(false)}>Keep batch</button>
              </div>
            </div>
          ) : null}
          {success ? <p className="workflow-feedback" role="status">{success}</p> : null}
          {error ? <div className="workflow-feedback workflow-feedback--error" role="alert"><span>{error}</span>{snapshot ? <button className="button button--secondary" type="button" disabled={busy} onClick={() => void update('status')}>Retry status</button> : null}</div> : null}
        </form>
      </div>
    </section>
  )
}

function NumberField({ id, label, value, disabled, onChange, error, max }: { id: string; label: string; value: string; disabled: boolean; onChange: (value: string) => void; error?: string | null; max?: string }) {
  return <div className="form-field"><label htmlFor={id}>{label}</label><input id={id} type="number" min="1" max={max} step="1" value={value} disabled={disabled} aria-invalid={error ? 'true' : undefined} aria-describedby={error ? `${id}-error` : undefined} onChange={(event) => onChange(event.target.value)} /><FieldError id={`${id}-error`} message={error ?? null} /></div>
}

function BatchStatusView({ snapshot, busy, onCancel, onRecover, onDownload, onDelete }: { snapshot: BatchSnapshot; busy: boolean; onCancel: () => void; onRecover: () => void; onDownload: () => void; onDelete: () => void }) {
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
        {snapshot.phase === 'ready' || snapshot.phase === 'error' ? <button className="button button--danger" type="button" disabled={busy} onClick={onDelete}>Delete batch</button> : null}
      </div>
    </section>
  )
}

const operations: Record<BatchToolId, string> = {
  'batch-image-convert': 'image.convert',
  'batch-image-resize': 'image.resize',
  'batch-image-compress': 'image.compress',
  'batch-office-to-pdf': 'office.to_pdf',
}

class OperationMismatch extends Error {
  constructor() { super('This recovery key belongs to a different batch tool.') }
}

function validateSnapshot(snapshot: BatchSnapshot, batchId: string, toolId: BatchToolId) {
  if (snapshot.id !== batchId) throw new Error('Batch identity mismatch')
  if (snapshot.operation !== operations[toolId]) throw new OperationMismatch()
}

function isUnavailable(error: unknown): boolean {
  return error instanceof ApiClientError && error.status === 404 && error.code === 'batch_not_found'
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
