import { afterEach, describe, expect, it, vi } from 'vitest'
import { createSummary, getSubtitleTracks, inspect } from './api'

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
})
