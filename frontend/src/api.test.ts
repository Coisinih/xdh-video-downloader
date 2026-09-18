import { afterEach, describe, expect, it, vi } from 'vitest'
import { inspect } from './api'

describe('inspection API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends the source URL to the inspection endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ inspection_id: 'i1', title: 'Demo', formats: [], expires_at: '2026-01-01T00:00:00Z' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await inspect('https://example.com/video')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/inspections', expect.objectContaining({ method: 'POST', body: JSON.stringify({ url: 'https://example.com/video' }) }))
  })
})
