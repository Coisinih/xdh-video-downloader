import { afterEach, describe, expect, it, vi } from 'vitest'
import { createDownload, createSummary, downloadSubtitle, getDownload, getSubtitleTracks, inspect } from './api'

describe('inspection API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends the source URL to the inspection endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ inspection_id: 'i1', title: 'Demo', formats: [], expires_at: '2026-01-01T00:00:00Z' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await inspect('https://example.com/video')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/inspections', expect.objectContaining({ method: 'POST', body: JSON.stringify({ url: 'https://example.com/video' }) }))
  })

  it('loads subtitle tracks from the isolated AI namespace', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ tracks: [] }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await getSubtitleTracks('i1')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/ai/inspections/i1/subtitle-tracks', expect.anything())
  })

  it('creates a summary without changing the download API contract', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 's1', status: 'queued', progress: 0, created_at: '2026-01-01T00:00:00Z' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await createSummary('i1', 'manual:zh-CN')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/ai/summaries', expect.objectContaining({ method: 'POST', body: JSON.stringify({ inspection_id: 'i1', subtitle_id: 'manual:zh-CN' }) }))
  })

  it('polls a server-side merged download when direct media lacks audio', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ id: 'd1', status: 'completed', progress: 100, delivery_url: '/api/v1/deliveries/token' }), { status: 200 })))
    vi.stubGlobal('fetch', fetchMock)
    await createDownload('i1', '137')
    await getDownload('d 1')
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/downloads', expect.objectContaining({ method: 'POST', body: JSON.stringify({ inspection_id: 'i1', format_id: '137', mode: 'direct' }) }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/downloads/d%201', expect.anything())
  })

  it('downloads an SRT subtitle blob for a subtitle track', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('subtitle', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const blob = await downloadSubtitle('i 1', 'manual:zh-CN', 'srt')
    expect(blob).toBeInstanceOf(Blob)
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/ai/inspections/i%201/subtitle-tracks/manual%3Azh-CN/download?format=srt')
  })
})
