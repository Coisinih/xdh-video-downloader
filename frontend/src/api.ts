export type Format = { id: string; label: string; ext: string; resolution?: string; filesize?: number; codec?: string; direct_available: boolean }
export type Inspection = { inspection_id: string; title: string; thumbnail?: string; duration?: number; author?: string; description?: string; platform?: string; view_count?: number; formats: Format[]; expires_at: string }
let csrfToken = ''
export const setCsrfToken = (value?: string) => { csrfToken = value || '' }
const idempotencyKey = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Content-Type', 'application/json')
  if (csrfToken && options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrfToken)
  const response = await fetch(path, { credentials: 'same-origin', ...options, headers })
  if (!response.ok) { const data = await response.json().catch(() => null); throw new Error(data?.detail || '请求失败，请稍后重试。') }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
export const inspect = (url: string) => request<Inspection>('/api/v1/inspections', { method: 'POST', body: JSON.stringify({ url }) })
export type DownloadTask = { id: string; status: 'queued' | 'downloading' | 'completed' | 'failed'; progress: number; error?: string; delivery_url?: string }
export const createDownload = (inspection_id: string, format_id: string) => request<{ mode: string; task_id?: string; delivery_url?: string }>('/api/v1/downloads', { method: 'POST', headers: { 'X-Idempotency-Key': idempotencyKey() }, body: JSON.stringify({ inspection_id, format_id, mode: 'direct' }) })
export const getDownload = (taskId: string) => request<DownloadTask>(`/api/v1/downloads/${encodeURIComponent(taskId)}`)

export type SubtitleTrack = { id: string; language: string; label: string; automatic: boolean }
export type TranscriptCue = { start: number; end: number; text: string }
export type OutlineSection = { title: string; summary: string }
export type KeyPoint = { title: string; detail: string }
export type MindMapNode = { title: string; children: MindMapNode[] }
export type SummaryResult = { overview: string; outline: OutlineSection[]; key_points: KeyPoint[]; keywords: string[]; mindmap: MindMapNode; mermaid: string; mindmap_markdown: string; source_language: string }
export type SummaryTask = { id: string; status: 'queued' | 'processing' | 'completed' | 'failed'; progress: number; error?: string; result?: SummaryResult; stream_text: string; created_at: string }
export type Citation = { start: number; end: number }
export type Answer = { answer: string; citations: Citation[]; created_at: string }
export type Membership = { is_vip: boolean; source?: 'one_time' | 'subscription'; expires_at?: string; subscription_status?: string; cancel_at_period_end: boolean }
export type CurrentUser = { id: string; email: string; csrf_token: string; membership: Membership; remaining_free_downloads: number | null }
export type BillingOrder = { id: string; purchase_type: 'one_time' | 'subscription'; status: string; amount_cents: number; currency: string; created_at: string }
export type BillingStatus = { configured: boolean; one_time_amount_cents: number; subscription_amount_cents: number; currency: string; membership: Membership; orders: BillingOrder[] }
export type BatchItem = { url: string; title?: string; status: string; progress: number; error?: string; delivery_url?: string }
export type BatchTask = { id: string; status: string; items: BatchItem[] }

export const getSubtitleTracks = (inspectionId: string) => request<{ tracks: SubtitleTrack[] }>(`/api/v1/ai/inspections/${encodeURIComponent(inspectionId)}/subtitle-tracks`)
export const getTranscript = (inspectionId: string, trackId: string) => request<{ track: SubtitleTrack; cues: TranscriptCue[] }>(`/api/v1/ai/inspections/${encodeURIComponent(inspectionId)}/subtitle-tracks/${encodeURIComponent(trackId)}`)
export type SubtitleDownloadFormat = "srt" | "txt"
export const downloadSubtitle = async (inspectionId: string, trackId: string, format: SubtitleDownloadFormat): Promise<Blob> => {
  const response = await fetch(`/api/v1/ai/inspections/${encodeURIComponent(inspectionId)}/subtitle-tracks/${encodeURIComponent(trackId)}/download?format=${format}`)
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    throw new Error(data?.detail || "字幕下载失败，请稍后重试。")
  }
  return response.blob()
}
export const createSummary = (inspectionId: string, subtitleId: string) => request<SummaryTask>('/api/v1/ai/summaries', { method: 'POST', body: JSON.stringify({ inspection_id: inspectionId, subtitle_id: subtitleId }) })
export const getSummary = (summaryId: string) => request<SummaryTask>(`/api/v1/ai/summaries/${encodeURIComponent(summaryId)}`)
export async function streamSummary(summaryId: string, onDelta: (text: string) => void): Promise<void> {
  const response = await fetch(`/api/v1/ai/summaries/${encodeURIComponent(summaryId)}/stream`, { credentials: 'same-origin', headers: { Accept: 'text/event-stream' } })
  if (!response.ok || !response.body) {
    const data = await response.json().catch(() => null)
    throw new Error(data?.detail || '无法建立 AI 总结实时连接。')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let event = ''
  let data = ''
  const dispatch = () => {
    if (event === 'delta' && data) {
      try { onDelta(JSON.parse(data).text || '') } catch { onDelta(data) }
    }
    if (event === 'error') {
      try { throw new Error(JSON.parse(data).message || 'AI 总结生成失败。') } catch (error) { if (error instanceof Error) throw error }
    }
    event = ''
    data = ''
  }
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const lines = buffer.split(/\r?\n/)
    buffer = done ? '' : lines.pop() || ''
    for (const line of lines) {
      if (!line) dispatch()
      else if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data += line.slice(5).trim()
    }
    if (done) { dispatch(); return }
  }
}
export const askSummaryQuestion = (summaryId: string, question: string) => request<Answer>(`/api/v1/ai/summaries/${encodeURIComponent(summaryId)}/questions`, { method: 'POST', body: JSON.stringify({ question }) })
export async function clearSummaryQuestions(summaryId: string): Promise<void> {
  const response = await fetch(`/api/v1/ai/summaries/${encodeURIComponent(summaryId)}/questions`, { method: 'DELETE', credentials: 'same-origin', headers: { 'X-CSRF-Token': csrfToken } })
  if (!response.ok) { const data = await response.json().catch(() => null); throw new Error(data?.detail || '清空会话失败，请稍后重试。') }
}

export const register = async (email: string, password: string) => {
  const user = await request<CurrentUser>('/api/v1/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) })
  setCsrfToken(user.csrf_token); return user
}
export const login = async (email: string, password: string) => {
  const user = await request<CurrentUser>('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
  setCsrfToken(user.csrf_token); return user
}
export const getCurrentUser = async () => {
  const user = await request<CurrentUser>('/api/v1/me')
  setCsrfToken(user.csrf_token); return user
}
export const logout = async () => { await request<void>('/api/v1/auth/logout', { method: 'POST' }); setCsrfToken() }
export const getBillingStatus = () => request<BillingStatus>('/api/v1/billing/status')
export const createCheckout = (purchase_type: 'one_time' | 'subscription') => request<{ order_id: string; checkout_url: string }>('/api/v1/billing/checkout', { method: 'POST', body: JSON.stringify({ purchase_type, request_key: idempotencyKey().replace(/\./g, '-') }) })
export const createBillingPortal = () => request<{ url: string }>('/api/v1/billing/portal', { method: 'POST' })
export const createBatchDownload = (urls: string[]) => request<BatchTask>('/api/v1/batch-downloads', { method: 'POST', body: JSON.stringify({ urls }) })
export const getBatchDownload = (id: string) => request<BatchTask>(`/api/v1/batch-downloads/${encodeURIComponent(id)}`)
export const translateSubtitle = (inspectionId: string, trackId: string, target_language: string) => request<{ source_language: string; target_language: string; cues: TranscriptCue[] }>(`/api/v1/ai/inspections/${encodeURIComponent(inspectionId)}/subtitle-tracks/${encodeURIComponent(trackId)}/translations`, { method: 'POST', body: JSON.stringify({ target_language }) })
export const createSupportTicket = (subject: string, message: string) => request<{ id: string; status: string }>('/api/v1/support/tickets', { method: 'POST', body: JSON.stringify({ subject, message }) })
