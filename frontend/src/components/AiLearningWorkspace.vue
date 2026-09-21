<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BotMessageSquare, BrainCircuit, ClipboardCopy, Download, Expand, FileText, GitBranch, Languages, ListTree, LoaderCircle, MessageCircleQuestion, RefreshCw, Send, Sparkles, X } from 'lucide-vue-next'
import { askSummaryQuestion, clearSummaryQuestions, createSummary, downloadSubtitle as fetchSubtitleFile, getSubtitleTracks, getSummary, getTranscript, streamSummary, translateSubtitle, type Answer, type Inspection, type MindMapNode, type SubtitleDownloadFormat, type SubtitleTrack, type SummaryTask, type TranscriptCue } from '../api'

const props = withDefaults(defineProps<{ inspection: Inspection; autoStart?: boolean }>(), { autoStart: true })
type Tab = 'summary' | 'transcript' | 'mindmap' | 'questions'

const activeTab = ref<Tab>('summary')
const tracks = ref<SubtitleTrack[]>([])
const selectedTrackId = ref('')
const cues = ref<TranscriptCue[]>([])
const summary = ref<SummaryTask | null>(null)
const streamedSummary = ref('')
const answers = ref<{ question: string; answer: Answer }[]>([])
const question = ref('')
const loadingTracks = ref(false)
const generating = ref(false)
const asking = ref(false)
const exportingMap = ref(false)
const fullscreenMap = ref(false)
const error = ref('')
const transcriptError = ref('')
const mapError = ref('')
const translating = ref(false)
const targetLanguage = ref('zh-CN')
const translatedCues = ref<TranscriptCue[]>([])
const mapHost = ref<HTMLDivElement | null>(null)
const fullscreenMapHost = ref<HTMLDivElement | null>(null)
const fullscreenTrigger = ref<HTMLButtonElement | null>(null)
const fullscreenClose = ref<HTMLButtonElement | null>(null)
let requestVersion = 0
let markmap: { destroy?: () => void; fit?: () => void } | null = null
let fullscreenMarkmap: { destroy?: () => void; fit?: () => void } | null = null

const hasTracks = computed(() => tracks.value.length > 0)
const selectedTrack = computed(() => tracks.value.find(track => track.id === selectedTrackId.value))
const usesAudioTranscription = computed(() => selectedTrack.value?.id === 'audio-transcription:automatic')
const isComplete = computed(() => summary.value?.status === 'completed' && Boolean(summary.value.result))
// This value is intentionally never constructed from result.outline: the
// stream is the one canonical version of the video outline.
const outlineMarkdown = computed(() => streamedSummary.value || summary.value?.stream_text || '')
const outlineHtml = computed(() => renderMarkdown(outlineMarkdown.value))
const timestamp = (seconds: number) => {
  const value = Math.floor(seconds)
  return `${String(Math.floor(value / 3600)).padStart(2, '0')}:${String(Math.floor(value % 3600 / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`
}
const treeChildren = (node: MindMapNode) => node.children || []

function escapeHtml(value: string) {
  return value.replace(/[&<>\"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[char]!)
}

function renderInline(value: string) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/_([^_]+)_/g, '<em>$1</em>')
    .replace(/\[([^\]]+)]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
}

function renderMarkdown(value: string) {
  const output: string[] = []
  let list: 'ul' | 'ol' | null = null
  let paragraph: string[] = []
  let inCodeBlock = false
  const closeList = () => { if (list) output.push(`</${list}>`); list = null }
  const closeParagraph = () => { if (paragraph.length) output.push(`<p>${renderInline(paragraph.join(' '))}</p>`); paragraph = [] }
  for (const rawLine of value.replace(/\r\n?/g, '\n').split('\n')) {
    const line = rawLine.trim()
    if (line.startsWith('```')) {
      closeParagraph(); closeList()
      output.push(inCodeBlock ? '</code></pre>' : '<pre><code>')
      inCodeBlock = !inCodeBlock
      continue
    }
    if (inCodeBlock) { output.push(`${escapeHtml(rawLine)}\n`); continue }
    if (!line) { closeParagraph(); closeList(); continue }
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    const ordered = line.match(/^\d+[.)]\s+(.+)$/)
    const unordered = line.match(/^[-*+]\s+(.+)$/)
    if (heading) {
      closeParagraph(); closeList()
      output.push(`<h${heading[1].length}>${renderInline(heading[2])}</h${heading[1].length}>`)
    } else if (ordered || unordered) {
      closeParagraph()
      const nextList = ordered ? 'ol' : 'ul'
      if (list !== nextList) { closeList(); output.push(`<${nextList}>`); list = nextList }
      output.push(`<li>${renderInline((ordered || unordered)![1])}</li>`)
    } else if (/^---+$/.test(line)) {
      closeParagraph(); closeList(); output.push('<hr>')
    } else if (line.startsWith('>')) {
      closeParagraph(); closeList(); output.push(`<blockquote>${renderInline(line.replace(/^>\s?/, ''))}</blockquote>`)
    } else {
      closeList()
      paragraph.push(line)
    }
  }
  closeParagraph(); closeList()
  if (inCodeBlock) output.push('</code></pre>')
  return output.join('')
}

async function loadTranscript(version = requestVersion) {
  if (!selectedTrackId.value) return
  transcriptError.value = ''
  try {
    const result = await getTranscript(props.inspection.inspection_id, selectedTrackId.value)
    if (version === requestVersion) cues.value = result.cues
  } catch (caught) {
    if (version === requestVersion) {
      cues.value = []
      transcriptError.value = caught instanceof Error ? caught.message : '字幕加载失败，请稍后重试。'
    }
  }
}

async function loadTracks() {
  const version = ++requestVersion
  tracks.value = []; selectedTrackId.value = ''; cues.value = []; translatedCues.value = []; summary.value = null; streamedSummary.value = ''
  answers.value = []; error.value = ''; transcriptError.value = ''; mapError.value = ''; generating.value = false; loadingTracks.value = true
  try {
    const result = await getSubtitleTracks(props.inspection.inspection_id)
    if (version !== requestVersion) return
    tracks.value = result.tracks
    // The highest-priority source subtitle is selected automatically. There is
    // deliberately no language selector, but transcript/export remain usable.
    selectedTrackId.value = result.tracks[0]?.id || ''
    await loadTranscript(version)
    // Release the subtitle-loading placeholder before awaiting the long-lived
    // SSE request, otherwise it masks every streamed Markdown update.
    loadingTracks.value = false
    if (props.autoStart && selectedTrackId.value && version === requestVersion) await generate(version)
  } catch (caught) {
    if (version === requestVersion) error.value = caught instanceof Error ? caught.message : '字幕信息加载失败，请稍后重试。'
  } finally {
    if (version === requestVersion) loadingTracks.value = false
  }
}

async function generate(version = requestVersion) {
  if (!selectedTrackId.value || generating.value) return
  error.value = ''; generating.value = true; answers.value = []; streamedSummary.value = ''; summary.value = null; activeTab.value = 'summary'
  try {
    const task = await createSummary(props.inspection.inspection_id, selectedTrackId.value)
    if (version !== requestVersion) return
    summary.value = task
    if (task.stream_text) streamedSummary.value = task.stream_text
    await streamSummary(task.id, chunk => { if (version === requestVersion) streamedSummary.value += chunk })
    if (version !== requestVersion) return
    const completed = await getSummary(task.id)
    if (version !== requestVersion) return
    summary.value = completed
    if (!streamedSummary.value && completed.stream_text) streamedSummary.value = completed.stream_text
    if (completed.status === 'failed') error.value = completed.error || '视频大纲生成失败，请稍后重试。'
    if (completed.status === 'completed') { await nextTick(); await renderMindmap() }
  } catch (caught) {
    if (version === requestVersion) error.value = caught instanceof Error ? caught.message : '视频大纲生成失败，请稍后重试。'
  } finally {
    if (version === requestVersion) generating.value = false
  }
}

async function ask() {
  if (!question.value.trim() || !summary.value || !isComplete.value || asking.value) return
  const content = question.value.trim(); question.value = ''; asking.value = true; error.value = ''
  try { answers.value.push({ question: content, answer: await askSummaryQuestion(summary.value.id, content) }) }
  catch (caught) { error.value = caught instanceof Error ? caught.message : '提问失败，请稍后重试。'; question.value = content }
  finally { asking.value = false }
}

async function clearConversation() {
  if (!summary.value) return
  try { await clearSummaryQuestions(summary.value.id); answers.value = [] }
  catch (caught) { error.value = caught instanceof Error ? caught.message : '清空会话失败，请稍后重试。' }
}

async function copy(value: string) {
  try { await navigator.clipboard.writeText(value) }
  catch { error.value = '无法复制内容，请检查浏览器权限。' }
}

async function downloadSubtitle(format: SubtitleDownloadFormat) {
  if (!selectedTrackId.value) return
  try {
    const blob = await fetchSubtitleFile(props.inspection.inspection_id, selectedTrackId.value, format)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = `${props.inspection.title.replace(/[\\/:*?"<>|]/g, '_')}.${format}`
    document.body.append(link); link.click(); link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '字幕下载失败，请稍后重试。' }
}

async function translateCurrentSubtitle() {
  if (!selectedTrackId.value) return
  translating.value = true; transcriptError.value = ''
  try {
    translatedCues.value = (await translateSubtitle(props.inspection.inspection_id, selectedTrackId.value, targetLanguage.value)).cues
  } catch (caught) { transcriptError.value = caught instanceof Error ? caught.message : '字幕翻译失败，请稍后重试。' }
  finally { translating.value = false }
}

function srtTime(seconds: number) {
  const milliseconds = Math.max(0, Math.round(seconds * 1000))
  const hours = Math.floor(milliseconds / 3600000)
  const minutes = Math.floor(milliseconds % 3600000 / 60000)
  const secs = Math.floor(milliseconds % 60000 / 1000)
  const ms = milliseconds % 1000
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')},${String(ms).padStart(3, '0')}`
}

function downloadTranslation(format: SubtitleDownloadFormat) {
  if (!translatedCues.value.length) return
  const content = format === 'srt'
    ? translatedCues.value.map((cue, index) => `${index + 1}\n${srtTime(cue.start)} --> ${srtTime(cue.end)}\n${cue.text}`).join('\n\n') + '\n'
    : translatedCues.value.map(cue => cue.text).join('\n') + '\n'
  const blob = new Blob([content], { type: format === 'srt' ? 'application/x-subrip;charset=utf-8' : 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob); const link = document.createElement('a')
  link.href = url; link.download = `${props.inspection.title.replace(/[\\/:*?"<>|]/g, '_')}.${targetLanguage.value}.${format}`
  document.body.append(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function renderMindmap(host = mapHost.value, fullscreen = false) {
  if (!host || !summary.value?.result?.mindmap_markdown) return
  try {
    const [{ Transformer }, { Markmap }] = await Promise.all([import('markmap-lib'), import('markmap-view')])
    if (fullscreen) fullscreenMarkmap?.destroy?.(); else markmap?.destroy?.()
    const { root } = new Transformer().transform(summary.value.result.mindmap_markdown)
    host.innerHTML = ''
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    const width = Math.max(host.clientWidth, fullscreen ? 1280 : 900)
    const height = Math.max(host.clientHeight, fullscreen ? 720 : 360)
    svg.setAttribute('width', String(width)); svg.setAttribute('height', String(height)); svg.style.width = `${width}px`; svg.style.height = `${height}px`
    host.append(svg)
    const rendered = Markmap.create(svg, { autoFit: false }, root)
    requestAnimationFrame(() => rendered.fit?.())
    if (fullscreen) fullscreenMarkmap = rendered; else markmap = rendered
    mapError.value = ''
  } catch {
    host.innerHTML = ''
    mapError.value = '思维导图加载失败，请查看下方结构化大纲。'
  }
}

async function openFullscreenMap() {
  fullscreenMap.value = true
  await nextTick(); await renderMindmap(fullscreenMapHost.value, true); fullscreenClose.value?.focus()
}
async function closeFullscreenMap() {
  fullscreenMap.value = false; fullscreenMarkmap?.destroy?.(); fullscreenMarkmap = null
  await nextTick(); fullscreenTrigger.value?.focus()
}

function exportedMindmapSvg() {
  const source = mapHost.value?.querySelector('svg')
  if (!source) throw new Error('思维导图尚未准备好，请稍后重试。')
  const clone = source.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.querySelector(':scope > g')?.removeAttribute('transform')
  clone.querySelectorAll('image').forEach(node => node.remove())
  return clone
}
function saveBlob(blob: Blob, extension: 'svg' | 'png') {
  const url = URL.createObjectURL(blob); const link = document.createElement('a')
  link.href = url; link.download = `${props.inspection.title.replace(/[\\/:*?"<>|]/g, '_') || 'mind-map'}.${extension}`
  document.body.append(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function downloadMindmapSvg() {
  try { saveBlob(new Blob([new XMLSerializer().serializeToString(exportedMindmapSvg())], { type: 'image/svg+xml;charset=utf-8' }), 'svg') }
  catch (caught) { mapError.value = caught instanceof Error ? caught.message : '思维导图导出失败，请稍后重试。' }
}
async function downloadMindmapImage() {
  exportingMap.value = true; mapError.value = ''
  try {
    const svg = exportedMindmapSvg(); const width = Number(svg.getAttribute('width')) || 1000; const height = Number(svg.getAttribute('height')) || 600
    const image = new Image(); const sourceUrl = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml;charset=utf-8' }))
    await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = () => reject(new Error('无法生成思维导图图片。')); image.src = sourceUrl })
    const canvas = document.createElement('canvas'); canvas.width = width * 3; canvas.height = height * 3
    const context = canvas.getContext('2d'); if (!context) throw new Error('当前浏览器不支持图片导出。')
    context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height); context.drawImage(image, 0, 0, canvas.width, canvas.height); URL.revokeObjectURL(sourceUrl)
    const png = await new Promise<Blob>((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('无法编码图片。')), 'image/png'))
    saveBlob(png, 'png')
  } catch (caught) { mapError.value = caught instanceof Error ? caught.message : '高清图片导出失败，请稍后重试。' }
  finally { exportingMap.value = false }
}

function handleKeydown(event: KeyboardEvent) { if (event.key === 'Escape' && fullscreenMap.value) { event.preventDefault(); void closeFullscreenMap() } }
watch(() => props.inspection.inspection_id, loadTracks, { immediate: true })
watch(activeTab, async tab => { if (tab === 'mindmap') { await nextTick(); await renderMindmap() } })
onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => { markmap?.destroy?.(); fullscreenMarkmap?.destroy?.(); window.removeEventListener('keydown', handleKeydown) })
</script>

<template>
  <section class="ai-workspace" aria-label="AI 视频学习助手">
    <header class="ai-header">
      <div>
        <p class="ai-eyebrow"><Sparkles :size="15" aria-hidden="true" />AI 视频学习助手</p>
        <h2>快速读懂视频核心内容</h2>
        <p>优先使用视频自带字幕；平台未提供字幕时，会使用 AI 音频转录生成大纲。</p>
      </div>
      <button class="ai-primary" type="button" :disabled="loadingTracks || !hasTracks || generating" @click="generate()">
        <LoaderCircle v-if="generating" class="spin" :size="15" aria-hidden="true" />
        <RefreshCw v-else :size="15" aria-hidden="true" />
        {{ generating ? '正在生成' : '重新生成' }}
      </button>
    </header>

    <p v-if="error" class="ai-error" role="alert">{{ error }}</p>
    <div class="ai-tabs" role="tablist" aria-label="AI 学习内容">
      <button v-for="tab in [{ id: 'summary', label: '视频大纲', icon: FileText }, { id: 'transcript', label: '字幕', icon: BotMessageSquare }, { id: 'mindmap', label: '思维导图', icon: GitBranch }, { id: 'questions', label: 'AI 问答', icon: MessageCircleQuestion }]" :key="tab.id" type="button" role="tab" :aria-selected="activeTab === tab.id" :class="{ active: activeTab === tab.id }" @click="activeTab = tab.id as Tab"><component :is="tab.icon" :size="15" aria-hidden="true" />{{ tab.label }}</button>
    </div>

    <div class="ai-panel" :aria-busy="loadingTracks || generating">
      <div v-if="loadingTracks" class="ai-loading" role="status"><LoaderCircle class="spin" :size="22" aria-hidden="true" /><strong>{{ usesAudioTranscription ? '正在生成 AI 音频转录' : '正在识别视频自带字幕' }}</strong><span>{{ usesAudioTranscription ? '首次使用会下载转录模型，较长视频需要几分钟，请保持页面打开。' : '识别完成后会自动开始生成视频大纲。' }}</span></div>
      <div v-else-if="!hasTracks" class="ai-placeholder"><BrainCircuit :size="26" aria-hidden="true" /><p>该视频没有可用的自带字幕，仍可继续下载视频。</p></div>

      <template v-else-if="activeTab === 'summary'">
        <article v-if="outlineMarkdown" class="outline-panel markdown-body" :aria-live="generating ? 'polite' : 'off'" v-html="outlineHtml"></article>
        <div v-else-if="generating || summary?.status === 'queued' || summary?.status === 'processing'" class="ai-loading" role="status"><LoaderCircle class="spin" :size="22" aria-hidden="true" /><strong>正在整理字幕并生成视频大纲</strong><span>内容会以 Markdown 样式实时显示在这里。</span></div>
        <div v-else-if="summary?.status === 'failed'" class="ai-placeholder"><ListTree :size="26" aria-hidden="true" /><p>视频大纲生成失败，请重新生成。</p></div>
        <div v-else class="ai-placeholder"><ListTree :size="26" aria-hidden="true" /><p>视频解析完成后，将自动生成视频大纲。</p></div>
      </template>

      <template v-else-if="activeTab === 'transcript'">
        <p v-if="transcriptError" class="ai-error" role="alert">{{ transcriptError }}</p>
        <template v-else-if="cues.length">
          <div class="panel-actions"><p>已加载 {{ cues.length }} 条{{ usesAudioTranscription ? ' AI 音频转录' : '视频自带字幕' }}。</p><div><button class="ai-secondary" type="button" @click="downloadSubtitle('srt')"><Download :size="15" aria-hidden="true" />原文 SRT</button><button class="ai-secondary" type="button" @click="downloadSubtitle('txt')"><Download :size="15" aria-hidden="true" />原文 TXT</button></div></div>
          <div class="translation-tools"><label for="translation-language">翻译为</label><select id="translation-language" v-model="targetLanguage"><option value="zh-CN">简体中文</option><option value="zh-TW">繁体中文</option><option value="en">英语</option><option value="ja">日语</option><option value="ko">韩语</option><option value="es">西班牙语</option><option value="fr">法语</option><option value="de">德语</option></select><button class="ai-primary" type="button" :disabled="translating" @click="translateCurrentSubtitle"><LoaderCircle v-if="translating" class="spin" :size="15" /><Languages v-else :size="15" />{{ translating ? '翻译中…' : 'DeepSeek 翻译' }}</button><template v-if="translatedCues.length"><button class="ai-secondary" type="button" @click="downloadTranslation('srt')"><Download :size="15" />译文 SRT</button><button class="ai-secondary" type="button" @click="downloadTranslation('txt')"><Download :size="15" />译文 TXT</button></template></div>
          <div class="transcript-list"><div v-for="cue in (translatedCues.length ? translatedCues : cues)" :key="`${cue.start}-${cue.end}-${cue.text}`" class="cue"><time>{{ timestamp(cue.start) }}</time><span>{{ cue.text }}</span></div></div>
        </template>
        <div v-else class="ai-placeholder"><BotMessageSquare :size="26" aria-hidden="true" /><p>暂无可展示字幕。</p></div>
      </template>

      <template v-else-if="activeTab === 'mindmap'">
        <template v-if="isComplete && summary?.result">
          <div class="panel-actions"><p>支持缩放、拖动与导出。</p><div><button ref="fullscreenTrigger" class="ai-secondary" type="button" @click="openFullscreenMap"><Expand :size="15" aria-hidden="true" />全屏查看</button><button class="ai-secondary" type="button" @click="downloadMindmapSvg"><Download :size="15" aria-hidden="true" />SVG</button><button class="ai-primary" type="button" :disabled="exportingMap" @click="downloadMindmapImage"><LoaderCircle v-if="exportingMap" class="spin" :size="15" aria-hidden="true" /><Download v-else :size="15" aria-hidden="true" />PNG</button></div></div>
          <p v-if="mapError" class="ai-error" role="alert">{{ mapError }}</p><div ref="mapHost" class="mindmap-host" aria-label="视频总结思维导图"></div>
          <details class="mindmap-fallback"><summary>查看结构化大纲</summary><ul class="mindmap-tree"><li><strong>{{ summary.result.mindmap.title }}</strong><ul><li v-for="node in treeChildren(summary.result.mindmap)" :key="node.title">{{ node.title }}</li></ul></li></ul></details>
        </template>
        <div v-else class="ai-placeholder"><GitBranch :size="26" aria-hidden="true" /><p>完成 AI 总结后即可查看思维导图。</p></div>
      </template>

      <template v-else>
        <div v-if="!isComplete" class="ai-placeholder"><MessageCircleQuestion :size="26" aria-hidden="true" /><p>完成 AI 总结后，即可针对视频内容提问。</p></div>
        <template v-else>
          <div v-if="answers.length" class="conversation"><article v-for="item in answers" :key="item.answer.created_at" class="answer"><p class="question">{{ item.question }}</p><p>{{ item.answer.answer }}</p><small v-if="item.answer.citations.length">字幕依据：{{ item.answer.citations.map(c => `${timestamp(c.start)}-${timestamp(c.end)}`).join('，') }}</small></article></div>
          <form class="question-form" @submit.prevent="ask"><label class="sr-only" for="ai-question">针对视频内容提问</label><input id="ai-question" v-model="question" :disabled="asking" maxlength="1000" placeholder="例如：这个视频最重要的结论是什么？"><button class="ai-primary" type="submit" :disabled="asking || !question.trim()"><LoaderCircle v-if="asking" class="spin" :size="15" aria-hidden="true" /><Send v-else :size="15" aria-hidden="true" />发送</button></form>
          <button v-if="answers.length" class="ai-link" type="button" @click="clearConversation"><ClipboardCopy :size="14" aria-hidden="true" />清空当前会话</button>
        </template>
      </template>
    </div>
  </section>
  <Teleport to="body"><section v-if="fullscreenMap" class="mindmap-modal" role="dialog" aria-modal="true" aria-label="全屏思维导图"><header><div><strong>视频总结思维导图</strong><span>可缩放、拖动浏览完整结构</span></div><button ref="fullscreenClose" class="modal-close" type="button" aria-label="关闭全屏思维导图" @click="closeFullscreenMap"><X :size="22" aria-hidden="true" /></button></header><div ref="fullscreenMapHost" class="mindmap-fullscreen-host" aria-label="全屏视频总结思维导图"></div></section></Teleport>
</template>

<style scoped>
.ai-workspace{margin:0;padding:18px;background:#fff;border:1px solid #dce6f7;border-radius:12px;box-shadow:0 8px 24px #263f680c}.ai-header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.ai-eyebrow{display:flex;align-items:center;gap:6px;margin:0 0 5px;color:#2563eb;font-size:13px;font-weight:700}.ai-header h2{margin:0;color:#1e293b;font-size:19px;line-height:1.35}.ai-header p:not(.ai-eyebrow){margin:5px 0 0;color:#667085;font-size:13px;line-height:1.55}.ai-primary,.ai-secondary{min-height:34px;border-radius:7px;padding:0 10px;display:inline-flex;align-items:center;justify-content:center;gap:5px;font-size:13px;font-weight:700;line-height:1;cursor:pointer;transition:background .15s ease,opacity .15s ease}.ai-primary{flex:none;border:1px solid #1d4ed8;background:#2563eb;color:#fff}.ai-primary:hover:not(:disabled){background:#1d4ed8}.ai-secondary{border:1px solid #c9dcff;background:#edf4ff;color:#245fc6}.ai-secondary:hover{background:#e1edff}.ai-primary:focus-visible,.ai-secondary:focus-visible,.ai-tabs button:focus-visible{outline:3px solid #93c5fd;outline-offset:2px}.ai-primary:disabled,.ai-secondary:disabled{cursor:not-allowed;opacity:.55}.ai-error{margin:12px 0;color:#b42318;font-size:13px;line-height:1.5}.ai-tabs{display:flex;gap:2px;margin-top:16px;border-bottom:1px solid #dce6f7;overflow-x:auto}.ai-tabs button{flex:none;white-space:nowrap;border:0;border-bottom:3px solid transparent;background:transparent;padding:10px 11px;color:#667085;display:inline-flex;align-items:center;gap:5px;font-size:13px;cursor:pointer}.ai-tabs button.active{color:#2563eb;border-bottom-color:#2563eb;font-weight:700}.ai-panel{padding-top:14px}.ai-loading,.ai-placeholder{min-height:176px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:9px;color:#667085;text-align:center;font-size:14px;line-height:1.6}.ai-loading strong{color:#24314a}.ai-placeholder p{max-width:360px;margin:0}.outline-panel{border:1px solid #e2e8f5;border-radius:9px;padding:15px 16px;background:#fbfdff}.markdown-body{color:#334155;font-size:14px;line-height:1.7;overflow-wrap:anywhere}.markdown-body :deep(h1),.markdown-body :deep(h2),.markdown-body :deep(h3){margin:0 0 10px;color:#1e293b;line-height:1.35}.markdown-body :deep(h1){font-size:19px}.markdown-body :deep(h2){font-size:17px}.markdown-body :deep(h3){font-size:15px}.markdown-body :deep(p){margin:0 0 10px}.markdown-body :deep(ol),.markdown-body :deep(ul){margin:0;padding-left:21px}.markdown-body :deep(li+li){margin-top:9px}.markdown-body :deep(strong){color:#1e3a70}.markdown-body :deep(code){padding:1px 4px;border-radius:4px;background:#edf4ff;color:#1d4ed8;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em}.markdown-body :deep(a){color:#1d4ed8;text-decoration:underline}.markdown-body :deep(blockquote){margin:0;padding-left:11px;border-left:3px solid #93c5fd;color:#52627a}.markdown-body :deep(pre){margin:0;overflow:auto;padding:10px;border-radius:6px;background:#f1f5f9}.markdown-body :deep(hr){border:0;border-top:1px solid #dce6f7;margin:12px 0}.panel-actions{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:12px}.panel-actions p{margin:0;color:#667085;font-size:13px}.panel-actions>div{display:flex;gap:7px;flex-wrap:wrap}.translation-tools{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:0 0 12px;padding:10px;border-radius:8px;background:#f5f8ff}.translation-tools label{font-size:13px;font-weight:700;color:#475569}.translation-tools select{min-height:34px;border:1px solid #c9d5e8;border-radius:7px;background:#fff;padding:0 8px}.transcript-list{max-height:430px;overflow:auto;border:1px solid #e2e8f5;border-radius:9px}.cue{padding:10px 12px;display:grid;grid-template-columns:74px minmax(0,1fr);gap:10px;border-bottom:1px solid #eef2f8;color:#354258;font-size:13px;line-height:1.6}.cue:last-child{border-bottom:0}.cue time{color:#2563eb;font-variant-numeric:tabular-nums;font-weight:700}.mindmap-host{min-height:260px;overflow:auto;border:1px solid #e2e8f5;border-radius:9px;padding:12px;background:#fbfdff}.mindmap-host :deep(svg){display:block;min-width:620px;max-width:none;overflow:visible}.mindmap-fallback{margin:12px 0;color:#536278;font-size:13px}.mindmap-tree{line-height:1.8}.conversation{display:grid;gap:10px;max-height:360px;overflow:auto;margin-bottom:12px}.answer{padding:12px;border:1px solid #e2e8f5;border-radius:9px;line-height:1.65;color:#3b4960;font-size:14px}.answer p{margin:0}.answer .question{margin-bottom:6px;color:#1e3a70;font-weight:700}.answer small{display:block;margin-top:8px;color:#667085}.question-form{display:flex;gap:8px}.question-form input{flex:1;min-width:0;min-height:36px;border:1px solid #bfcbe0;border-radius:7px;padding:0 10px;font-size:14px}.ai-link{display:inline-flex;align-items:center;gap:5px;margin-top:6px;border:0;background:transparent;color:#5573a9;padding:8px 0;font-size:13px;text-decoration:underline;cursor:pointer}.spin{animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}.mindmap-modal{position:fixed;z-index:1000;inset:0;background:#f8fbff;display:grid;grid-template-rows:auto minmax(0,1fr);padding:20px}.mindmap-modal header{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:0 0 16px;border-bottom:1px solid #dce6f7}.mindmap-modal header div{display:grid;gap:3px}.mindmap-modal header strong{font-size:20px;color:#1e293b}.mindmap-modal header span{color:#667085;font-size:14px}.modal-close{width:44px;height:44px;display:grid;place-items:center;border:1px solid #c9dcff;border-radius:8px;background:#fff;color:#245fc6;cursor:pointer}.mindmap-fullscreen-host{min-height:0;overflow:auto;padding:28px;background:#fff;border:1px solid #e2e8f5;border-top:0}.mindmap-fullscreen-host :deep(svg){display:block;min-width:1000px;min-height:620px;max-width:none;overflow:visible}@media(max-width:640px){.ai-workspace{padding:15px}.ai-header{gap:12px}.ai-header h2{font-size:18px}.ai-primary{padding:0 9px}.outline-panel{padding:13px}.markdown-body{font-size:14px}.question-form{align-items:stretch}.mindmap-modal{padding:12px}.mindmap-fullscreen-host{padding:16px}.mindmap-fullscreen-host :deep(svg){min-width:760px;min-height:520px;max-width:none}}
</style>
