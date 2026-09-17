import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../api/client'
import type { BatchSnapshot } from '../api/types'
import { BatchToolWorkspace } from './BatchToolWorkspace'

function snapshot(overrides: Partial<BatchSnapshot> = {}): BatchSnapshot {
  return {
    id: 'batch-1',
    operation: 'image.convert',
    attempt: 1,
    phase: 'processing',
    status: 'running',
    progress_percent: 50,
    cancellation_requested: false,
    summary: { total: 2, pending: 1, running: 0, completed: 1, failed: 0, cancelled: 0, processed: 1, remaining: 1 },
    items: [
      { id: 'item-1', position: 0, descriptor: 'first.png', status: 'completed', result_descriptor: '0001-first.jpg', failure: null },
      { id: 'item-2', position: 1, descriptor: 'second.png', status: 'pending', result_descriptor: null, failure: null },
    ],
    session_error: null,
    can_cancel: true,
    can_recover: false,
    can_download: false,
    ...overrides,
  }
}

function client(initial = snapshot()): ApiClient {
  return {
    getMetadata: vi.fn(),
    getHealth: vi.fn(),
    postMultipartForBlob: vi.fn(),
    createBatch: vi.fn().mockResolvedValue(initial),
    getBatchStatus: vi.fn().mockResolvedValue(initial),
    cancelBatch: vi.fn().mockResolvedValue(initial),
    recoverBatch: vi.fn().mockResolvedValue(initial),
    downloadBatch: vi.fn().mockResolvedValue({ blob: new Blob(['zip']), contentType: 'application/zip', contentDisposition: 'attachment; filename="results.zip"' }),
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((complete) => {
    resolve = complete
  })
  return { promise, resolve }
}

afterEach(() => vi.useRealTimers())

describe('batch workspace', () => {
  it('preserves selected order, submits configuration, polls, and renders terminal items', async () => {
    vi.useFakeTimers()
    const accepted = snapshot()
    const complete = snapshot({
      phase: 'ready', status: 'completed', progress_percent: 100, can_cancel: false, can_download: true,
      summary: { total: 2, pending: 0, running: 0, completed: 2, failed: 0, cancelled: 0, processed: 2, remaining: 0 },
      items: accepted.items.map((item) => ({ ...item, status: 'completed', result_descriptor: item.position ? '0002-second.jpg' : '0001-first.jpg' })),
    })
    const api = client(accepted)
    vi.mocked(api.getBatchStatus).mockResolvedValue(complete)
    render(<BatchToolWorkspace toolId="batch-image-convert" onBack={vi.fn()} client={api} />)

    const files = [new File(['a'], 'first.png'), new File(['b'], 'second.png')]
    fireEvent.change(screen.getByLabelText('Image files'), { target: { files } })
    expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual(expect.arrayContaining([expect.stringContaining('first.png'), expect.stringContaining('second.png')]))
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
    await act(async () => Promise.resolve())
    expect(api.createBatch).toHaveBeenCalledWith('/api/v1/batches/images/convert', expect.any(FormData))
    const submitted = vi.mocked(api.createBatch).mock.calls[0][1]
    expect(submitted.getAll('file').map((file) => (file as File).name)).toEqual(['first.png', 'second.png'])
    expect(submitted.get('format')).toBe('jpeg')
    expect(screen.getAllByText('50%')).toHaveLength(2)
    expect(screen.getByText('1 / 2 processed')).toBeVisible()

    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    expect(api.getBatchStatus).toHaveBeenCalledWith('batch-1')
    expect(screen.getAllByText('100%')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Download ZIP' })).toBeEnabled()
    expect(screen.getByText('0002-second.jpg')).toBeVisible()
  })

  it('cancels and recovers the same batch while keeping partial download available', async () => {
    const accepted = snapshot()
    const cancelled = snapshot({
      phase: 'ready', status: 'partial', cancellation_requested: true, can_cancel: false, can_recover: true, can_download: true,
      summary: { total: 2, pending: 0, running: 0, completed: 1, failed: 0, cancelled: 1, processed: 2, remaining: 0 },
      items: [accepted.items[0], { ...accepted.items[1], status: 'cancelled' }],
    })
    const api = client(accepted)
    vi.mocked(api.cancelBatch).mockResolvedValue(cancelled)
    vi.mocked(api.getBatchStatus).mockRejectedValueOnce(new Error('private')).mockResolvedValue(cancelled)
    vi.mocked(api.recoverBatch).mockResolvedValue(snapshot({ attempt: 2 }))
    render(<BatchToolWorkspace toolId="batch-image-convert" onBack={vi.fn()} client={api} />)
    fireEvent.change(screen.getByLabelText('Image files'), { target: { files: [new File(['a'], 'first.png')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
    await screen.findByRole('button', { name: 'Cancel' })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(await screen.findByText(/Cancellation requested/)).toBeVisible()
    expect(screen.getByText('cancelled')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Download ZIP' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Retry failed/cancelled items' }))
    await waitFor(() => expect(api.recoverBatch).toHaveBeenCalledWith('batch-1'))
  })

  it('submits the full resize and maximum-size compression configurations', async () => {
    const resizeClient = client(snapshot({ phase: 'ready', status: 'completed', can_cancel: false }))
    const { unmount } = render(<BatchToolWorkspace toolId="batch-image-resize" onBack={vi.fn()} client={resizeClient} />)
    fireEvent.change(screen.getByLabelText('Image files'), { target: { files: [new File(['a'], 'one.png')] } })
    fireEvent.change(screen.getByLabelText('Maximum height'), { target: { value: '900' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /Allow upscaling/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
    await waitFor(() => expect(resizeClient.createBatch).toHaveBeenCalled())
    const resizeData = vi.mocked(resizeClient.createBatch).mock.calls[0][1]
    expect(Object.fromEntries(resizeData.entries())).toMatchObject({ max_width: '1200', max_height: '900', allow_upscale: 'true' })
    unmount()

    const compressClient = client(snapshot({ phase: 'ready', status: 'completed', can_cancel: false }))
    render(<BatchToolWorkspace toolId="batch-image-compress" onBack={vi.fn()} client={compressClient} />)
    fireEvent.change(screen.getByLabelText('Image files'), { target: { files: [new File(['a'], 'one.png')] } })
    fireEvent.click(screen.getByLabelText('Maximum file size'))
    fireEvent.change(screen.getByLabelText('Maximum size (KB)'), { target: { value: '25' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
    await waitFor(() => expect(compressClient.createBatch).toHaveBeenCalled())
    const compressData = vi.mocked(compressClient.createBatch).mock.calls[0][1]
    expect(compressData.get('max_bytes')).toBe('25600')
    expect(compressData.has('quality')).toBe(false)
  })

  it('keeps the last snapshot after a polling error and retries the same batch ID', async () => {
    vi.useFakeTimers()
    const api = client()
    vi.mocked(api.getBatchStatus).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(
      snapshot({ phase: 'ready', status: 'completed', progress_percent: 100, can_cancel: false }),
    )
    render(<BatchToolWorkspace toolId="batch-image-convert" onBack={vi.fn()} client={api} />)
    fireEvent.change(screen.getByLabelText('Image files'), { target: { files: [new File(['a'], 'one.png')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
    await act(async () => Promise.resolve())
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    expect(screen.getAllByText('50%')).toHaveLength(2)
    expect(screen.getByRole('alert')).toHaveTextContent('Status could not be refreshed.')
    fireEvent.click(screen.getByRole('button', { name: 'Retry status' }))
    await act(async () => Promise.resolve())
    expect(api.getBatchStatus).toHaveBeenLastCalledWith('batch-1')
    expect(screen.getAllByText('100%')).toHaveLength(2)
  })

  it('does not start a scheduled poll while cancellation is in flight and resumes afterward', async () => {
    vi.useFakeTimers()
    const api = client()
    const cancellation = deferred<BatchSnapshot>()
    vi.mocked(api.cancelBatch).mockReturnValue(cancellation.promise)
    render(<BatchToolWorkspace toolId="batch-image-convert" onBack={vi.fn()} client={api} />)
    fireEvent.change(screen.getByLabelText('Image files'), { target: { files: [new File(['a'], 'one.png')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
    await act(async () => Promise.resolve())

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    expect(api.getBatchStatus).not.toHaveBeenCalled()
    cancellation.resolve(snapshot({ phase: 'cancelling', cancellation_requested: true, can_cancel: false }))
    await act(async () => Promise.resolve())
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    expect(api.getBatchStatus).toHaveBeenCalledTimes(1)
  })

  it('does not begin a user action while an automatic poll is unresolved', async () => {
    vi.useFakeTimers()
    const api = client()
    const polling = deferred<BatchSnapshot>()
    vi.mocked(api.getBatchStatus).mockReturnValueOnce(polling.promise)
    render(<BatchToolWorkspace toolId="batch-image-convert" onBack={vi.fn()} client={api} />)
    fireEvent.change(screen.getByLabelText('Image files'), { target: { files: [new File(['a'], 'one.png')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
    await act(async () => Promise.resolve())
    await act(async () => { vi.advanceTimersByTime(800); await Promise.resolve() })

    const cancel = screen.getByRole('button', { name: 'Cancel' })
    expect(cancel).toBeDisabled()
    fireEvent.click(cancel)
    expect(api.cancelBatch).not.toHaveBeenCalled()
    polling.resolve(snapshot())
    await act(async () => Promise.resolve())
    expect(cancel).toBeEnabled()
  })

  it('serializes Retry status with automatic polling and resumes after it resolves', async () => {
    vi.useFakeTimers()
    const api = client()
    const manualStatus = deferred<BatchSnapshot>()
    vi.mocked(api.getBatchStatus)
      .mockRejectedValueOnce(new Error('offline'))
      .mockReturnValueOnce(manualStatus.promise)
      .mockResolvedValueOnce(snapshot())
    render(<BatchToolWorkspace toolId="batch-image-convert" onBack={vi.fn()} client={api} />)
    fireEvent.change(screen.getByLabelText('Image files'), { target: { files: [new File(['a'], 'one.png')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
    await act(async () => Promise.resolve())
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })

    fireEvent.click(screen.getByRole('button', { name: 'Retry status' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    expect(api.getBatchStatus).toHaveBeenCalledTimes(2)
    manualStatus.resolve(snapshot())
    await act(async () => Promise.resolve())
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    expect(api.getBatchStatus).toHaveBeenCalledTimes(3)
  })

  it('clears scheduled polling when unmounted', async () => {
    vi.useFakeTimers()
    const api = client()
    const { unmount } = render(<BatchToolWorkspace toolId="batch-image-convert" onBack={vi.fn()} client={api} />)
    fireEvent.change(screen.getByLabelText('Image files'), { target: { files: [new File(['a'], 'one.png')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
    await act(async () => Promise.resolve())
    unmount()
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    expect(api.getBatchStatus).not.toHaveBeenCalled()
  })

  it.each([
    ['batch_packaging_failed', 'Retry packaging'],
    ['batch_execution_failed', 'Retry batch'],
    [null, 'Retry failed/cancelled items'],
  ])('uses the truthful recovery label for %s', async (code, label) => {
    const recoverable = snapshot({
      phase: code ? 'error' : 'ready',
      status: 'partial',
      can_cancel: false,
      can_recover: true,
      session_error: code ? { code, message: 'The batch needs recovery.' } : null,
    })
    const api = client(recoverable)
    render(<BatchToolWorkspace toolId="batch-image-convert" onBack={vi.fn()} client={api} />)
    fireEvent.change(screen.getByLabelText('Image files'), { target: { files: [new File(['a'], 'one.png')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Start batch' }))
    expect(await screen.findByRole('button', { name: label })).toBeVisible()
  })
})
