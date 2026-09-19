<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BotMessageSquare, BrainCircuit, ClipboardCopy, Download, Expand, FileText, GitBranch, LoaderCircle, MessageCircleQuestion, RefreshCw, Send, Sparkles, X } from 'lucide-vue-next'
import { askSummaryQuestion, clearSummaryQuestions, createSummary, downloadSubtitle as fetchSubtitleFile, getSubtitleTracks, getSummary, getTranscript, streamSummary, type Answer, type Inspection, type MindMapNode, type SubtitleDownloadFormat, type SubtitleTrack, type SummaryTask, type TranscriptCue } from '../api'

const props = defineProps<{ inspection: Inspection }>()
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
const error = ref('')
const transcriptError = ref('')
const mapHost = ref<HTMLDivElement | null>(null)
const fullscreenMapHost = ref<HTMLDivElement | null>(null)
const fullscreenMap = ref(false)
const mapError = ref('')
const exportingMap = ref(false)
const fullscreenTrigger = ref<HTMLButtonElement | null>(null)
const fullscreenClose = ref<HTMLButtonElement | null>(null)
let pollTimer: number | undefined
let markmap: { destroy?: () => void; fit?: () => void } | null = null
let fullscreenMarkmap: { destroy?: () => void; fit?: () => void } | null = null

const selectedTrack = computed(() => tracks.value.find(track => track.id === selectedTrackId.value))
const isComplete = computed(() => summary.value?.status === 'completed' && summary.value.result)
const hasTracks = computed(() => tracks.value.length > 0)
const timestamp = (seconds: number) => {
  const value = Math.floor(seconds)
  return `${String(Math.floor(value / 3600)).padStart(2, '0')}:${String(Math.floor(value % 3600 / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`
}
const treeChildren = (node: MindMapNode) => node.children || []

function stopPolling() { if (pollTimer !== undefined) { window.clearInterval(pollTimer); pollTimer = undefined } }
async function loadTranscript() {
  if (!selectedTrackId.value) return
  transcriptError.value = ''
  try { cues.value = (await getTranscript(props.inspection.inspection_id, selectedTrackId.value)).cues } catch (caught) { cues.value = []; transcriptError.value = caught instanceof Error ? caught.message : '字幕加载失败。' }
}
async function loadTracks() {
  stopPolling(); tracks.value = []; selectedTrackId.value = ''; cues.value = []; summary.value = null; answers.value = []; error.value = ''; transcriptError.value = ''; loadingTracks.value = true
  try {
    const result = await getSubtitleTracks(props.inspection.inspection_id)
    tracks.value = result.tracks
    selectedTrackId.value = result.tracks[0]?.id || ''
    await loadTranscript()
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '字幕信息加载失败。' } finally { loadingTracks.value = false }
}
async function renderMindmap(host = mapHost.value, fullscreen = false) {
  if (!host || !summary.value?.result?.mindmap_markdown) return
  try {
    const [{ Transformer }, { Markmap }] = await Promise.all([import('markmap-lib'), import('markmap-view')])
    if (fullscreen) fullscreenMarkmap?.destroy?.()
    else markmap?.destroy?.()
    const { root } = new Transformer().transform(summary.value.result.mindmap_markdown)
    host.innerHTML = ''
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    const width = Math.max(host.clientWidth, fullscreen ? 1280 : 1000)
    const height = Math.max(host.clientHeight, fullscreen ? 720 : 480)
    svg.setAttribute('width', String(width))
    svg.setAttribute('height', String(height))
    svg.style.width = width + 'px'
    svg.style.height = height + 'px'
    host.append(svg)
    const rendered = Markmap.create(svg, { autoFit: false }, root)
    requestAnimationFrame(() => rendered.fit?.())
    if (fullscreen) fullscreenMarkmap = rendered
    else markmap = rendered
    mapError.value = ''
  } catch {
    host.innerHTML = ''
    mapError.value = '思维导图加载失败，请查看下方结构化大纲。'
  }
}
async function pollSummary() {
  if (!summary.value) return
  try {
    summary.value = await getSummary(summary.value.id)
    if (summary.value.status === 'completed' || summary.value.status === 'failed') { stopPolling(); generating.value = false; if (summary.value.status === 'completed') { await nextTick(); await renderMindmap() } }
  } catch (caught) { stopPolling(); generating.value = false; error.value = caught instanceof Error ? caught.message : '获取总结结果失败。' }
}
async function generate() {
  if (!selectedTrackId.value) return
  error.value = ''; generating.value = true; answers.value = []; streamedSummary.value = ''
  try {
    summary.value = await createSummary(props.inspection.inspection_id, selectedTrackId.value)
    await streamSummary(summary.value.id, chunk => { streamedSummary.value += chunk })
    await pollSummary()
  } catch (caught) { generating.value = false; error.value = caught instanceof Error ? caught.message : 'AI summary could not be created.' }
}
async function ask() {
  if (!question.value.trim() || !summary.value || !isComplete.value) return
  const content = question.value.trim(); question.value = ''; asking.value = true; error.value = ''
  try { answers.value.push({ question: content, answer: await askSummaryQuestion(summary.value.id, content) }) } catch (caught) { error.value = caught instanceof Error ? caught.message : '提问失败。'; question.value = content } finally { asking.value = false }
}
async function clearConversation() { if (!summary.value) return; try { await clearSummaryQuestions(summary.value.id); answers.value = [] } catch (caught) { error.value = caught instanceof Error ? caught.message : '清空会话失败。' } }
async function copy(value: string) { try { await navigator.clipboard.writeText(value) } catch { error.value = '无法复制内容，请检查浏览器权限。' } }
async function downloadSubtitle(format: SubtitleDownloadFormat) {
  if (!selectedTrackId.value) return
  try {
    const blob = await fetchSubtitleFile(props.inspection.inspection_id, selectedTrackId.value, format)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = props.inspection.title.replace(/[\\/:*?"<>|]/g, '_') + '.' + format
    document.body.append(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '字幕下载失败，请稍后重试。' }
}
async function openFullscreenMap() {
  fullscreenMap.value = true
  await nextTick()
  await renderMindmap(fullscreenMapHost.value, true)
  fullscreenClose.value?.focus()
}
async function closeFullscreenMap() {
  fullscreenMap.value = false
  fullscreenMarkmap?.destroy?.()
  fullscreenMarkmap = null
  await nextTick()
  fullscreenTrigger.value?.focus()
}
function prepareMindmapSvg(source: SVGSVGElement) {
  const clone = source.cloneNode(true) as SVGSVGElement
  // Markmap applies reader pan/zoom to this outer group. Its local bounding
  // box is stable, while screen coordinates would export only the current view.
  const tree = source.querySelector(':scope > g') as SVGGElement | null
  const fallbackWidth = Number.parseFloat(source.getAttribute('width') || '') || 1000
  const fallbackHeight = Number.parseFloat(source.getAttribute('height') || '') || 600
  let minX = 0; let minY = 0; let maxX = fallbackWidth; let maxY = fallbackHeight
  try {
    if (tree) {
      const box = tree.getBBox()
      minX = box.x; minY = box.y
      maxX = box.x + box.width; maxY = box.y + box.height
    }
  } catch { /* fall back to the rendered SVG viewport */ }
  const sourceLabels = Array.from(source.querySelectorAll('foreignObject'))
  const cloneLabels = Array.from(clone.querySelectorAll('foreignObject'))
  sourceLabels.forEach((label, index) => {
    const exportedLabel = cloneLabels[index]
    const textContent = label.textContent?.trim().replace(/\s+/g, ' ')
    if (!exportedLabel || !textContent) return
    const x = Number.parseFloat(label.getAttribute('x') || '0') || 0
    const y = Number.parseFloat(label.getAttribute('y') || '0') || 0
    const height = Number.parseFloat(label.getAttribute('height') || '0') || 20
    const style = window.getComputedStyle(label.firstElementChild || label)
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text')
    // Replacing the XHTML foreignObject inside its node group keeps text and
    // structure lines in precisely the same coordinate system. It also avoids
    // browser-specific foreignObject/canvas rendering and tainted canvases.
    text.setAttribute('x', String(x))
    text.setAttribute('y', String(y + height / 2))
    text.setAttribute('dominant-baseline', 'middle')
    text.setAttribute('xml:space', 'preserve')
    text.setAttribute('font-family', style.fontFamily || 'Arial, sans-serif')
    text.setAttribute('font-size', style.fontSize || '16px')
    text.setAttribute('font-weight', style.fontWeight || '400')
    text.setAttribute('fill', style.color || '#1f2937')
    text.textContent = textContent
    exportedLabel.replaceWith(text)
  })
  // The exported image should contain the whole tree, not the user's current
  // interactive pan/zoom state.
  clone.querySelector(':scope > g')?.removeAttribute('transform')
  const padding = 48
  const viewX = minX - padding; const viewY = minY - padding
  const width = Math.max(1, maxX - minX + padding * 2)
  const height = Math.max(1, maxY - minY + padding * 2)
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(Math.ceil(width)))
  clone.setAttribute('height', String(Math.ceil(height)))
  clone.setAttribute('viewBox', [viewX, viewY, width, height].join(' '))
  clone.style.width = width + 'px'
  clone.style.height = height + 'px'
  clone.querySelectorAll('image').forEach(node => node.remove())
  clone.querySelectorAll('[href], [xlink\\:href]').forEach(node => {
    const href = node.getAttribute('href') || node.getAttributeNS('http://www.w3.org/1999/xlink', 'href') || ''
    if (/^(https?:|data:)/i.test(href)) node.removeAttribute('href')
    node.removeAttributeNS('http://www.w3.org/1999/xlink', 'href')
  })
  clone.querySelectorAll('style').forEach(style => { style.textContent = (style.textContent || '').replace(/url\\([^)]*\\)/gi, '') })
  return { clone, width, height }
}
function downloadMindmapSvg() {
  const source = mapHost.value?.querySelector('svg')
  if (!source) { mapError.value = '思维导图尚未准备好，请稍后重试。'; return }
  const { clone } = prepareMindmapSvg(source)
  const blob = new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = (props.inspection.title.replace(/[\\/:*?"<>|]/g, '_') || 'mind-map') + '.svg'
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function downloadMindmapImage() {
  const source = mapHost.value?.querySelector('svg')
  if (!source) { mapError.value = '思维导图尚未准备好，请稍后重试。'; return }
  exportingMap.value = true
  mapError.value = ''
  try {
    const { clone: svg, width, height } = prepareMindmapSvg(source)
    const serializer = new XMLSerializer()
    const image = new Image()
    const objectUrl = URL.createObjectURL(new Blob([serializer.serializeToString(svg)], { type: 'image/svg+xml;charset=utf-8' }))
    await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = () => reject(new Error('无法生成思维导图图片。')); image.src = objectUrl })
    const scale = 3
    const canvas = document.createElement('canvas')
    canvas.width = Math.ceil(width * scale)
    canvas.height = Math.ceil(height * scale)
    const context = canvas.getContext('2d')
    if (!context) throw new Error('当前浏览器不支持图片导出。')
    context.fillStyle = '#ffffff'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    URL.revokeObjectURL(objectUrl)
    const png = await new Promise<Blob>((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('无法编码思维导图图片。')), 'image/png'))
    const link = document.createElement('a')
    link.href = URL.createObjectURL(png)
    link.download = (props.inspection.title.replace(/[\\/:*?"<>|]/g, '_') || 'mind-map') + '.png'
    document.body.append(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(link.href), 1000)
  } catch (caught) { mapError.value = caught instanceof Error ? caught.message : '高清图片导出失败，请稍后重试。' } finally { exportingMap.value = false }
}

watch(() => props.inspection.inspection_id, loadTracks, { immediate: true })
watch(selectedTrackId, loadTranscript)
watch(activeTab, async tab => { if (tab === 'mindmap') { await nextTick(); await renderMindmap() } })
function handleKeydown(event: KeyboardEvent) { if (event.key === 'Escape' && fullscreenMap.value) { event.preventDefault(); void closeFullscreenMap() } }
onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => { stopPolling(); markmap?.destroy?.(); fullscreenMarkmap?.destroy?.(); window.removeEventListener('keydown', handleKeydown) })
</script>

<template>
  <section class="ai-workspace" aria-label="AI 视频学习助手">
    <header class="ai-header"><div><p class="ai-eyebrow"><Sparkles :size="16"/> AI 视频学习助手</p><h2>快速读懂视频核心内容</h2><p>仅基于平台已有字幕生成总结和问答，不会上传或转录视频音频。</p></div><button class="ai-copy" type="button" :disabled="!summary?.result" @click="summary?.result && copy(summary.result.overview)"><ClipboardCopy :size="16"/>复制摘要</button></header>
    <p v-if="error" class="ai-error" role="alert">{{ error }}</p>
    <div class="ai-controls"><label for="subtitle-track">字幕语言</label><select id="subtitle-track" v-model="selectedTrackId" :disabled="loadingTracks || !hasTracks"><option v-for="track in tracks" :key="track.id" :value="track.id">{{ track.label }}</option></select><span v-if="loadingTracks" class="ai-status"><LoaderCircle class="spin" :size="16"/>正在获取字幕</span><span v-else-if="!hasTracks" class="ai-empty">该视频没有可用字幕，仍可使用下载功能。</span><button class="ai-primary" type="button" :disabled="!hasTracks || generating" @click="generate"><LoaderCircle v-if="generating" class="spin" :size="17"/><Sparkles v-else :size="17"/>{{ generating ? '正在生成总结' : '生成 AI 总结' }}</button></div>
    <div class="ai-tabs" role="tablist" aria-label="AI 学习内容"><button v-for="tab in [{ id: 'summary', label: '总结', icon: FileText }, { id: 'transcript', label: '字幕/转录', icon: BotMessageSquare }, { id: 'mindmap', label: '思维导图', icon: GitBranch }, { id: 'questions', label: 'AI 问答', icon: MessageCircleQuestion }]" :key="tab.id" type="button" role="tab" :aria-selected="activeTab === tab.id" :class="{ active: activeTab === tab.id }" @click="activeTab = tab.id as Tab"><component :is="tab.icon" :size="16"/>{{ tab.label }}</button></div>
    <div class="ai-panel">
      <pre v-if="generating && streamedSummary" class="streamed-summary">{{ streamedSummary }}</pre>
      <template v-if="activeTab === 'summary'"><div v-if="generating || summary?.status === 'queued' || summary?.status === 'processing'" class="ai-loading"><LoaderCircle class="spin" :size="24"/><strong>正在整理字幕并生成学习笔记</strong><span>完成后会自动展示摘要、大纲、要点和思维导图。</span></div><template v-else-if="summary?.status === 'failed'"><p class="ai-error">{{ summary.error }}</p><button class="ai-secondary" type="button" @click="generate"><RefreshCw :size="16"/>重新生成</button></template><template v-else-if="summary?.result"><article class="overview"><h3>一句话摘要</h3><p>{{ summary.result.overview }}</p></article><div class="summary-grid"><article><h3>视频大纲</h3><ol><li v-for="section in summary.result.outline" :key="section.title"><strong>{{ section.title }}</strong><p>{{ section.summary }}</p></li></ol></article><article><h3>核心知识点</h3><ul><li v-for="point in summary.result.key_points" :key="point.title"><strong>{{ point.title }}</strong><p>{{ point.detail }}</p></li></ul></article></div><div class="keywords"><span v-for="keyword in summary.result.keywords" :key="keyword">{{ keyword }}</span></div></template><div v-else class="ai-placeholder"><BrainCircuit :size="28"/><p>选择字幕后生成 AI 总结，快速掌握视频内容。</p></div></template>
      <template v-else-if="activeTab === 'transcript'"><p v-if="transcriptError" class="ai-error">{{ transcriptError }}</p><template v-else-if="cues.length"><div class="transcript-actions"><p>已加载 {{ cues.length }} 条字幕，可导出 SRT 或纯文本。</p><div><button class="ai-secondary" type="button" @click="downloadSubtitle('srt')"><Download :size="16"/>下载 SRT</button><button class="ai-secondary" type="button" @click="downloadSubtitle('txt')"><Download :size="16"/>下载 TXT</button></div></div><div class="transcript-list"><button v-for="cue in cues" :key="`${cue.start}-${cue.end}-${cue.text}`" type="button" class="cue" :aria-label="`字幕 ${timestamp(cue.start)}`"><time>{{ timestamp(cue.start) }}</time><span>{{ cue.text }}</span></button></div></template><div v-else class="ai-placeholder"><BotMessageSquare :size="28"/><p>暂无可展示字幕。</p></div></template>
      <template v-else-if="activeTab === 'mindmap'"><template v-if="summary?.result"><div class="mindmap-actions"><p>可缩放、拖动查看；全屏模式可获得更宽阔的阅读空间。</p><div><button ref="fullscreenTrigger" class="ai-secondary" type="button" @click="openFullscreenMap"><Expand :size="16"/>全屏查看</button><button class="ai-secondary" type="button" @click="downloadMindmapSvg"><Download :size="16"/>下载 SVG</button><button class="ai-primary" type="button" :disabled="exportingMap" @click="downloadMindmapImage"><LoaderCircle v-if="exportingMap" class="spin" :size="16"/><Download v-else :size="16"/>下载高清 PNG</button></div></div><p v-if="mapError" class="ai-error" role="alert">{{ mapError }}</p><div ref="mapHost" class="mindmap-host" aria-label="视频总结思维导图"></div><details class="mindmap-fallback"><summary>查看结构化大纲（图表加载失败时可用）</summary><ul class="mindmap-tree"><li><strong>{{ summary.result.mindmap.title }}</strong><ul><li v-for="node in treeChildren(summary.result.mindmap)" :key="node.title">{{ node.title }}</li></ul></li></ul></details><button class="ai-secondary" type="button" @click="copy(summary.result.mermaid)"><ClipboardCopy :size="16"/>复制 Mermaid</button></template><div v-else class="ai-placeholder"><GitBranch :size="28"/><p>生成总结后即可查看思维导图。</p></div></template>
      <template v-else><div v-if="!isComplete" class="ai-placeholder"><MessageCircleQuestion :size="28"/><p>完成 AI 总结后，即可针对视频内容提问。</p></div><template v-else><div class="conversation"><article v-for="item in answers" :key="item.answer.created_at" class="answer"><p class="question">{{ item.question }}</p><p>{{ item.answer.answer }}</p><small v-if="item.answer.citations.length">字幕依据：{{ item.answer.citations.map(c => `${timestamp(c.start)}-${timestamp(c.end)}`).join('，') }}</small></article></div><form class="question-form" @submit.prevent="ask"><label class="sr-only" for="ai-question">针对视频内容提问</label><input id="ai-question" v-model="question" :disabled="asking" maxlength="1000" placeholder="例如：这个视频最重要的结论是什么？"><button class="ai-primary" type="submit" :disabled="asking || !question.trim()"><LoaderCircle v-if="asking" class="spin" :size="16"/><Send v-else :size="16"/>发送</button></form><button v-if="answers.length" class="ai-link" type="button" @click="clearConversation">清空当前会话</button></template></template>
    </div>
  </section>
  <Teleport to="body"><section v-if="fullscreenMap" class="mindmap-modal" role="dialog" aria-modal="true" aria-label="全屏思维导图"><header><div><strong>视频总结思维导图</strong><span>可缩放、拖动浏览完整结构</span></div><button ref="fullscreenClose" class="modal-close" type="button" aria-label="关闭全屏思维导图" @click="closeFullscreenMap"><X :size="22"/></button></header><div ref="fullscreenMapHost" class="mindmap-fullscreen-host" aria-label="全屏视频总结思维导图"></div></section></Teleport>
</template>

<style scoped>
.ai-workspace{max-width:1040px;margin:0 auto 42px;padding:30px;background:#fff;border:1px solid #dce6f7;border-radius:14px;box-shadow:0 12px 32px #263f6810}.ai-header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.ai-eyebrow{display:flex;align-items:center;gap:7px;color:#2563eb;font-weight:700;margin:0 0 8px}.ai-header h2{margin:0;font-size:24px}.ai-header p:not(.ai-eyebrow){color:#667085;margin:8px 0 0;line-height:1.6}.ai-controls{margin:24px 0 18px;padding:14px;background:#f6f9ff;border-radius:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}.ai-controls label{font-weight:700}.ai-controls select{min-height:42px;border:1px solid #bfceed;border-radius:7px;padding:0 10px;background:#fff;color:#24314a}.ai-primary,.ai-secondary,.ai-copy{min-height:42px;border:0;border-radius:7px;padding:0 15px;display:inline-flex;align-items:center;justify-content:center;gap:7px;font-weight:700}.ai-primary{background:#2563eb;color:#fff}.ai-primary:disabled,.ai-copy:disabled{opacity:.55;cursor:not-allowed}.ai-secondary,.ai-copy{background:#edf4ff;color:#245fc6;border:1px solid #c9dcff}.ai-copy{flex:none}.ai-status,.ai-empty{font-size:14px;color:#61718b;display:inline-flex;align-items:center;gap:5px}.ai-empty{color:#93620d}.ai-tabs{display:flex;gap:4px;border-bottom:1px solid #dce6f7;overflow:auto}.ai-tabs button{white-space:nowrap;border:0;border-bottom:3px solid transparent;background:transparent;padding:12px 15px;color:#667085;display:inline-flex;align-items:center;gap:6px}.ai-tabs button.active{color:#2563eb;border-bottom-color:#2563eb;font-weight:700}.ai-panel{padding-top:22px}.ai-loading,.ai-placeholder{min-height:170px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;color:#667085;text-align:center}.ai-loading strong{color:#24314a}.overview{border-left:4px solid #2563eb;background:#f6f9ff;padding:16px 18px;border-radius:0 9px 9px 0}.overview h3,.summary-grid h3{margin:0 0 9px;color:#1e293b}.overview p{margin:0;line-height:1.75}.summary-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}.summary-grid article{border:1px solid #e2e8f5;border-radius:10px;padding:16px}.summary-grid ol,.summary-grid ul{margin:0;padding-left:20px}.summary-grid li+li{margin-top:14px}.summary-grid p{margin:5px 0 0;color:#5d6b80;line-height:1.6}.keywords{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.keywords span{background:#edf4ff;color:#245fc6;border-radius:99px;padding:6px 11px;font-size:13px}.transcript-list{max-height:520px;overflow:auto;border:1px solid #e2e8f5;border-radius:9px}.cue{width:100%;border:0;border-bottom:1px solid #eef2f8;background:#fff;text-align:left;padding:12px 15px;display:grid;grid-template-columns:72px 1fr;gap:12px;color:#354258;line-height:1.6}.cue:hover{background:#f6f9ff}.cue time{color:#2563eb;font-variant-numeric:tabular-nums;font-weight:700}.mindmap-host{overflow:auto;min-height:240px;border:1px solid #e2e8f5;border-radius:9px;padding:16px;background:#fbfdff}.mindmap-host :deep(svg){min-width:620px;max-width:none}.mindmap-fallback{margin:14px 0;color:#536278}.mindmap-tree{line-height:1.8}.conversation{display:grid;gap:12px;max-height:410px;overflow:auto;margin-bottom:14px}.answer{padding:14px;border:1px solid #e2e8f5;border-radius:9px;line-height:1.65;color:#3b4960}.answer p{margin:0}.answer .question{font-weight:700;color:#1e3a70;margin-bottom:7px}.answer small{display:block;color:#667085;margin-top:9px}.question-form{display:flex;gap:10px}.question-form input{flex:1;min-width:0;min-height:44px;border:1px solid #bfcbe0;border-radius:7px;padding:0 12px}.ai-link{border:0;background:transparent;color:#5573a9;padding:10px 0;text-decoration:underline}.ai-error{color:#b42318;margin:12px 0}.spin{animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}@media(max-width:800px){.ai-workspace{margin:0 16px 28px;padding:20px}.ai-header{flex-direction:column}.ai-copy{width:100%}.summary-grid{grid-template-columns:1fr}.question-form{align-items:stretch}.question-form .ai-primary{padding:0 12px}.ai-tabs button{padding:12px}.ai-controls{align-items:stretch}.ai-controls select,.ai-controls .ai-primary{width:100%}}
.streamed-summary{max-height:360px;overflow:auto;white-space:pre-wrap;margin:0 0 16px;padding:16px;border:1px solid #c9dcff;border-radius:9px;background:#f8fbff;color:#26354d;line-height:1.7;text-align:left;font:14px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace}.mindmap-host :deep(svg){min-width:620px;min-height:280px}
.transcript-actions,.mindmap-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px}.transcript-actions p,.mindmap-actions p{margin:0;color:#61718b;font-size:14px;line-height:1.55}.mindmap-actions>div{display:flex;gap:8px;flex-wrap:wrap}.mindmap-modal{position:fixed;z-index:1000;inset:0;background:#f8fbff;display:grid;grid-template-rows:auto minmax(0,1fr);padding:20px}.mindmap-modal header{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:0 0 16px;border-bottom:1px solid #dce6f7}.mindmap-modal header div{display:grid;gap:3px}.mindmap-modal header strong{font-size:20px;color:#1e293b}.mindmap-modal header span{color:#667085;font-size:14px}.modal-close{width:44px;height:44px;display:grid;place-items:center;border:1px solid #c9dcff;border-radius:8px;background:#fff;color:#245fc6}.mindmap-fullscreen-host{min-height:0;overflow:auto;padding:28px;background:#fff;border:1px solid #e2e8f5;border-top:0}.mindmap-fullscreen-host :deep(svg){min-width:1000px;min-height:620px;max-width:none}@media(max-width:800px){.mindmap-modal{padding:12px}.mindmap-fullscreen-host{padding:16px}.mindmap-fullscreen-host :deep(svg){min-width:760px;min-height:520px}}
.mindmap-host,.mindmap-fullscreen-host{overflow:auto;overscroll-behavior:contain}.mindmap-host :deep(svg),.mindmap-fullscreen-host :deep(svg){display:block;max-width:none;max-height:none;overflow:visible}
</style>
