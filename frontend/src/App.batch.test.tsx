import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ApiClientError } from './api/client'
import type { ApiClient } from './api/client'
import type { BatchSnapshot, BatchSessionHandle } from './api/types'
import { BatchToolWorkspace } from './batch/BatchToolWorkspace'
import { encodeRecoveryKey } from './batch/recoveryKey'

const id = '12345678-1234-4234-8234-123456789abc'
const token = 'private_capability_123'
const health = () => new Promise<never>(() => {})
function snapshot(overrides: Partial<BatchSnapshot> = {}): BatchSnapshot {
  return { id, operation: 'image.convert', attempt: 1, phase: 'ready', status: 'completed', progress_percent: 100,
    cancellation_requested: false, summary: { total: 1, pending: 0, running: 0, completed: 1, failed: 0, cancelled: 0, processed: 1, remaining: 0 },
    items: [{ id: 'item', position: 0, descriptor: 'one.png', status: 'completed', result_descriptor: 'one.jpg', failure: null }],
    session_error: null, can_cancel: false, can_recover: true, can_download: true, ...overrides }
}
function api(): ApiClient {
  return { getMetadata: vi.fn(), getHealth: vi.fn(), postMultipartForBlob: vi.fn(),
    createBatch: vi.fn().mockResolvedValue({ snapshot: snapshot(), accessToken: token }),
    getBatchStatus: vi.fn().mockResolvedValue(snapshot()), cancelBatch: vi.fn().mockResolvedValue(snapshot()), recoverBatch: vi.fn().mockResolvedValue(snapshot()),
    downloadBatch: vi.fn().mockResolvedValue({ blob: new Blob(['zip']), contentDisposition: null }), deleteBatch: vi.fn().mockResolvedValue(undefined) }
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((r) => { resolve = r }); return { promise, resolve } }
async function open(name = 'Batch image convert') { fireEvent.click(screen.getByRole('button', { name: `Open ${name}` })); }
function back() { fireEvent.click(screen.getByRole('button', { name: /Back to tools/ })); }
async function start() {
  fireEvent.change(screen.getByLabelText('Image files'), { target: { files: [new File(['a'], 'one.png')] } })
  fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Copy recovery key' })).toBeEnabled())
}
function paste(key = encodeRecoveryKey({ snapshot: snapshot(), accessToken: token })) {
  fireEvent.click(screen.getByRole('button', { name: 'Resume a batch' }))
  fireEvent.change(screen.getByLabelText('Recovery key'), { target: { value: key } })
  fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
}
const missing = () => new ApiClientError('private error', { kind: 'http', status: 404, code: 'batch_not_found' })
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('App batch continuity', () => {
  it('retains two per-tool handles, refreshes on reentry, and deletes only the matching handle', async () => {
    const client = api()
    const office = snapshot({ id: '22345678-1234-4234-8234-123456789abc', operation: 'office.to_pdf' })
    vi.mocked(client.createBatch).mockResolvedValueOnce({ snapshot: snapshot(), accessToken: token }).mockResolvedValueOnce({ snapshot: office, accessToken: 'office_token' })
    vi.mocked(client.getBatchStatus).mockImplementation(async (batchId) => batchId === id ? snapshot() : office)
    render(<App checkHealth={health} batchClient={client} />)
    await open(); await start(); back(); await open('Batch Office to PDF')
    fireEvent.change(screen.getByLabelText('Office files'), { target: { files: [new File(['a'], 'one.docx')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
    await screen.findByRole('button', { name: 'Delete batch' }); back(); await open()
    expect(screen.getByRole('button', { name: 'Delete batch' })).toBeDisabled()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete batch' })).toBeEnabled())
    expect(client.getBatchStatus).toHaveBeenCalledWith(id, token)
    expect(screen.queryByRole('button', { name: 'Start batch' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Delete batch' })); fireEvent.click(screen.getByRole('button', { name: 'Delete now' }))
    await screen.findByText('Batch deleted from the server.')
    back(); await open('Batch Office to PDF')
    await waitFor(() => expect(client.getBatchStatus).toHaveBeenCalledWith(office.id, 'office_token'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete batch' })).toBeEnabled())
    expect(client.createBatch).toHaveBeenCalledTimes(2)
    expect(document.body.innerHTML).not.toContain(token)
    expect(document.body.innerHTML).not.toContain('office_token')
  })

  it('blocks Back during unresolved creation and restores the accepted session', async () => {
    const client = api(); const pending = deferred<BatchSessionHandle>()
    vi.mocked(client.createBatch).mockReturnValue(pending.promise)
    render(<App checkHealth={health} batchClient={client} />); await open()
    fireEvent.change(screen.getByLabelText('Image files'), { target: { files: [new File(['a'], 'one.png')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
    expect(screen.getByRole('button', { name: /Back to tools/ })).toBeDisabled()
    await act(async () => pending.resolve({ snapshot: snapshot(), accessToken: token }))
    expect(screen.getByRole('button', { name: /Back to tools/ })).toBeEnabled()
    back(); await open()
    await waitFor(() => expect(client.getBatchStatus).toHaveBeenCalledWith(id, token))
    expect(client.createBatch).toHaveBeenCalledTimes(1)
  })

  it.each([new Error('offline'), new ApiClientError('secret', { kind: 'http', status: 503 }), new ApiClientError('bad', { kind: 'malformed-response' })])('preserves the handle after transient reentry failure %#', async (failure) => {
    const client = api(); render(<App checkHealth={health} batchClient={client} />); await open(); await start(); back()
    vi.mocked(client.getBatchStatus).mockRejectedValueOnce(failure)
    await open(); expect(await screen.findByRole('alert')).toHaveTextContent('Could not reconnect to this batch. Retry status.')
    expect(screen.getByRole('button', { name: 'Delete batch' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Retry status' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete batch' })).toBeEnabled())
    expect(vi.mocked(client.getBatchStatus).mock.calls).toEqual([[id, token], [id, token]])
    expect(client.createBatch).toHaveBeenCalledTimes(1)
  })

  it('clears expired handles on reentry and stops polling', async () => {
    const client = api(); render(<App checkHealth={health} batchClient={client} />); await open(); await start(); back()
    vi.mocked(client.getBatchStatus).mockRejectedValue(missing()); await open()
    await screen.findByText('This batch is no longer available. It may have expired or been deleted.')
    expect(screen.getByRole('button', { name: 'Start batch' })).toBeVisible()
    back(); await open(); expect(client.getBatchStatus).toHaveBeenCalledTimes(1)
  })

  it('revalidates the returned identity and operation without replacing a retained handle', async () => {
    const client = api(); render(<App checkHealth={health} batchClient={client} />); await open(); await start(); back()
    vi.mocked(client.getBatchStatus).mockResolvedValueOnce(snapshot({ operation: 'image.resize' })); await open()
    await screen.findByRole('alert'); expect(screen.getByRole('button', { name: 'Download ZIP' })).toBeDisabled()
    back(); await open(); await waitFor(() => expect(screen.getByRole('button', { name: 'Download ZIP' })).toBeEnabled())
    expect(client.createBatch).toHaveBeenCalledTimes(1)
  })

  it('stops inactive polling, revalidates, resumes one timer and serializes actions in StrictMode', async () => {
    vi.useFakeTimers(); const client = api()
    const running = snapshot({ phase: 'processing', can_cancel: true, can_download: false })
    vi.mocked(client.createBatch).mockResolvedValue({ snapshot: running, accessToken: token })
    vi.mocked(client.getBatchStatus).mockResolvedValue(running)
    render(<StrictMode><App checkHealth={health} batchClient={client} /></StrictMode>); await open()
    fireEvent.change(screen.getByLabelText('Image files'), { target: { files: [new File(['a'], 'one.png')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' })); await act(async () => {})
    back(); await act(async () => { await vi.advanceTimersByTimeAsync(2400) }); expect(client.getBatchStatus).not.toHaveBeenCalled()
    await open(); await act(async () => { await vi.advanceTimersByTimeAsync(0) }); expect(client.getBatchStatus).toHaveBeenCalledTimes(1)
    const pending = deferred<BatchSnapshot>(); vi.mocked(client.getBatchStatus).mockReturnValueOnce(pending.promise)
    await act(async () => { await vi.advanceTimersByTimeAsync(800) }); expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    await act(async () => { await vi.advanceTimersByTimeAsync(2400) }); expect(client.getBatchStatus).toHaveBeenCalledTimes(2)
    await act(async () => pending.resolve(snapshot()))
    await act(async () => { await vi.advanceTimersByTimeAsync(2400) }); expect(client.getBatchStatus).toHaveBeenCalledTimes(2)
    expect(client.createBatch).toHaveBeenCalledTimes(1)
  })
})

describe('explicit recovery', () => {
  it('copies only on click, waits for clipboard success, and handles clipboard failure safely', async () => {
    const pending = deferred<void>(); const writeText = vi.fn().mockReturnValueOnce(pending.promise).mockRejectedValueOnce(new Error(token))
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const client = api(); render(<App checkHealth={health} batchClient={client} />); await open(); await start()
    expect(writeText).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Copy recovery key' }))
    expect(screen.queryByText('Recovery key copied. Keep it private.')).not.toBeInTheDocument()
    expect(writeText).toHaveBeenCalledWith(`DFB1:${id}:${token}`)
    await act(async () => pending.resolve()); await screen.findByText('Recovery key copied. Keep it private.')
    fireEvent.click(screen.getByRole('button', { name: 'Copy recovery key' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not copy the recovery key. Try again.')
    expect(document.body.innerHTML).not.toContain(token)
    expect(screen.getByRole('button', { name: 'Download ZIP' })).toBeEnabled()
    vi.unstubAllGlobals()
  })

  it('authenticates a pasted password field using GET only and clears the form after success', async () => {
    const client = api(); render(<App checkHealth={health} batchClient={client} />); await open(); paste()
    expect(screen.getByLabelText('Recovery key')).toHaveAttribute('type', 'password')
    expect(screen.getByLabelText('Recovery key')).toHaveAttribute('autocomplete', 'off')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Download ZIP' })).toBeEnabled())
    expect(client.getBatchStatus).toHaveBeenCalledWith(id, token)
    for (const method of [client.createBatch, client.cancelBatch, client.recoverBatch, client.deleteBatch, client.downloadBatch]) expect(method).not.toHaveBeenCalled()
    expect(screen.queryByLabelText('Recovery key')).not.toBeInTheDocument()
    expect(document.body.innerHTML).not.toContain(token)
    fireEvent.click(screen.getByRole('button', { name: 'Retry failed/cancelled items' }))
    await waitFor(() => expect(client.recoverBatch).toHaveBeenCalledWith(id, token))
  })

  it.each(['wrong-tool', 'wrong-id', '404', 'network', 'malformed'])('refuses unsafe attachment: %s', async (kind) => {
    const client = api()
    if (kind === 'wrong-tool') vi.mocked(client.getBatchStatus).mockResolvedValue(snapshot({ operation: 'office.to_pdf' }))
    if (kind === 'wrong-id') vi.mocked(client.getBatchStatus).mockResolvedValue(snapshot({ id: 'other' }))
    if (kind === '404') vi.mocked(client.getBatchStatus).mockRejectedValue(missing())
    if (kind === 'network') vi.mocked(client.getBatchStatus).mockRejectedValue(new Error(token))
    render(<App checkHealth={health} batchClient={client} />); await open(); paste(kind === 'malformed' ? 'bad' : undefined)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(kind === 'wrong-tool' ? 'This recovery key belongs to a different batch tool.' : kind === '404' ? 'This batch is unavailable or the recovery key is invalid.' : kind === 'malformed' ? 'Enter a valid DocuForge recovery key.' : 'Could not reach DocuForge. Retry with the same recovery key.')
    if (kind === 'malformed') expect(client.getBatchStatus).not.toHaveBeenCalled()
    expect(client.createBatch).not.toHaveBeenCalled(); expect(client.cancelBatch).not.toHaveBeenCalled(); expect(client.deleteBatch).not.toHaveBeenCalled()
    expect(screen.queryByRole('region', { name: 'Batch status' })).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain(token)
    if (kind === 'network') {
      vi.mocked(client.getBatchStatus).mockResolvedValue(snapshot())
      fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
      await waitFor(() => expect(client.getBatchStatus).toHaveBeenCalledTimes(2))
      expect(vi.mocked(client.getBatchStatus).mock.calls[1]).toEqual([id, token])
    }
  })

  it.each(['dismiss', 'navigate'])('ignores late resume after %s', async (action) => {
    const client = api(); const pending = deferred<BatchSnapshot>(); vi.mocked(client.getBatchStatus).mockReturnValue(pending.promise)
    render(<App checkHealth={health} batchClient={client} />); await open(); paste()
    if (action === 'dismiss') fireEvent.click(screen.getByRole('button', { name: 'Dismiss resume' }))
    else { back(); await open('Batch image resize') }
    await act(async () => pending.resolve(snapshot()))
    expect(screen.queryByRole('region', { name: 'Batch status' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Recovery key')).not.toBeInTheDocument()
    if (action === 'navigate') { back(); await open(); expect(screen.getByRole('button', { name: 'Start batch' })).toBeVisible() }
  })

  it('supports keyboard-only private resume with heading focus and labeled errors', async () => {
    const user = userEvent.setup(); const client = api()
    render(<App checkHealth={health} batchClient={client} />)
    const opener = screen.getByRole('button', { name: 'Open Batch image convert' })
    opener.focus(); await user.keyboard('{Enter}')
    expect(screen.getByRole('heading', { level: 1, name: 'Batch image convert' })).toHaveFocus()
    await user.tab(); expect(screen.getByRole('button', { name: 'Resume a batch' })).toHaveFocus()
    await user.keyboard('{Enter}'); await user.tab()
    expect(screen.getByLabelText('Recovery key')).toHaveFocus()
    await user.keyboard(encodeRecoveryKey({ snapshot: snapshot(), accessToken: token }))
    await user.tab(); await user.keyboard('{Enter}')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Download ZIP' })).toBeEnabled())
  })

  it('preserves the original capability for cancel, download and failed deletion after reentry', async () => {
    const client = api(); const running = snapshot({ phase: 'processing', can_cancel: true })
    render(<App checkHealth={health} batchClient={client} />); await open(); await start(); back()
    vi.mocked(client.getBatchStatus).mockResolvedValueOnce(running); await open()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(client.cancelBatch).toHaveBeenCalledWith(id, token))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Download ZIP' })).toBeEnabled())
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    fireEvent.click(screen.getByRole('button', { name: 'Download ZIP' }))
    await waitFor(() => expect(client.downloadBatch).toHaveBeenCalledWith(id, token))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete batch' })).toBeEnabled())
    vi.mocked(client.deleteBatch).mockRejectedValueOnce(new Error(token))
    fireEvent.click(screen.getByRole('button', { name: 'Delete batch' })); fireEvent.click(screen.getByRole('button', { name: 'Delete now' }))
    await screen.findByRole('alert'); back(); await open()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete batch' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Delete batch' })); fireEvent.click(screen.getByRole('button', { name: 'Delete now' }))
    await screen.findByText('Batch deleted from the server.')
    expect(vi.mocked(client.deleteBatch).mock.calls).toEqual([[id, token], [id, token]])
    click.mockRestore()
  })

  it('does not write live credentials to storage, URLs or logs', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    const log = vi.spyOn(console, 'log'); const warn = vi.spyOn(console, 'warn'); const error = vi.spyOn(console, 'error')
    const client = api(); render(<App checkHealth={health} batchClient={client} />); await open(); await start(); back(); await open()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Download ZIP' })).toBeEnabled())
    expect(storage).not.toHaveBeenCalled()
    expect(window.location.href).not.toContain(token)
    expect(document.cookie).not.toContain(token)
    expect(document.body.innerHTML).not.toContain(token)
    expect(JSON.stringify([...log.mock.calls, ...warn.mock.calls, ...error.mock.calls])).not.toContain(token)
  })

  it('does not share accepted handles across independent React roots', async () => {
    const client = api(); const first = render(<App checkHealth={health} batchClient={client} />); await open(); await start(); first.unmount()
    render(<App checkHealth={health} batchClient={client} />); await open(); expect(screen.getByRole('button', { name: 'Start batch' })).toBeVisible()
    expect(client.getBatchStatus).not.toHaveBeenCalled()
  })

  it('does not publish a delayed reentry response after unmount', async () => {
    const client = api(); const pending = deferred<BatchSnapshot>(); vi.mocked(client.getBatchStatus).mockReturnValue(pending.promise)
    const change = vi.fn(); const clear = vi.fn()
    const view = render(<BatchToolWorkspace toolId="batch-image-convert" session={{ snapshot: snapshot(), accessToken: token }} onSessionChange={change} onSessionClear={clear} onBack={vi.fn()} client={client} />)
    await waitFor(() => expect(client.getBatchStatus).toHaveBeenCalledTimes(1)); view.unmount()
    await act(async () => pending.resolve(snapshot())); expect(change).not.toHaveBeenCalled(); expect(clear).not.toHaveBeenCalled()
  })
})
