<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { BotMessageSquare, BrainCircuit, ClipboardCopy, FileText, GitBranch, LoaderCircle, MessageCircleQuestion, RefreshCw, Send, Sparkles } from 'lucide-vue-next'
import { askSummaryQuestion, clearSummaryQuestions, createSummary, getSubtitleTracks, getSummary, getTranscript, streamSummary, type Answer, type Inspection, type MindMapNode, type SubtitleTrack, type SummaryTask, type TranscriptCue } from '../api'

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
let pollTimer: number | undefined
let markmap: { destroy?: () => void; fit?: () => void } | null = null

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
async function renderMindmap() {
  if (!mapHost.value || !summary.value?.result?.mindmap_markdown) return
  try {
    const [{ Transformer }, { Markmap }] = await Promise.all([import('markmap-lib'), import('markmap-view')])
    markmap?.destroy?.()
    const { root } = new Transformer().transform(summary.value.result.mindmap_markdown)
    mapHost.value.innerHTML = ''
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    mapHost.value.append(svg)
    markmap = Markmap.create(svg, { autoFit: true }, root)
  } catch { if (mapHost.value) mapHost.value.innerHTML = '' }
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

watch(() => props.inspection.inspection_id, loadTracks, { immediate: true })
watch(selectedTrackId, loadTranscript)
watch(activeTab, async tab => { if (tab === 'mindmap') { await nextTick(); await renderMindmap() } })
onBeforeUnmount(() => { stopPolling(); markmap?.destroy?.() })
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
      <template v-else-if="activeTab === 'transcript'"><p v-if="transcriptError" class="ai-error">{{ transcriptError }}</p><div v-else-if="cues.length" class="transcript-list"><button v-for="cue in cues" :key="`${cue.start}-${cue.end}-${cue.text}`" type="button" class="cue" :aria-label="`字幕 ${timestamp(cue.start)}`"><time>{{ timestamp(cue.start) }}</time><span>{{ cue.text }}</span></button></div><div v-else class="ai-placeholder"><BotMessageSquare :size="28"/><p>暂无可展示字幕。</p></div></template>
      <template v-else-if="activeTab === 'mindmap'"><template v-if="summary?.result"><div ref="mapHost" class="mindmap-host" aria-label="视频总结思维导图"></div><details class="mindmap-fallback"><summary>查看结构化大纲（图表加载失败时可用）</summary><ul class="mindmap-tree"><li><strong>{{ summary.result.mindmap.title }}</strong><ul><li v-for="node in treeChildren(summary.result.mindmap)" :key="node.title">{{ node.title }}</li></ul></li></ul></details><button class="ai-secondary" type="button" @click="copy(summary.result.mermaid)"><ClipboardCopy :size="16"/>复制 Mermaid</button></template><div v-else class="ai-placeholder"><GitBranch :size="28"/><p>生成总结后即可查看思维导图。</p></div></template>
      <template v-else><div v-if="!isComplete" class="ai-placeholder"><MessageCircleQuestion :size="28"/><p>完成 AI 总结后，即可针对视频内容提问。</p></div><template v-else><div class="conversation"><article v-for="item in answers" :key="item.answer.created_at" class="answer"><p class="question">{{ item.question }}</p><p>{{ item.answer.answer }}</p><small v-if="item.answer.citations.length">字幕依据：{{ item.answer.citations.map(c => `${timestamp(c.start)}-${timestamp(c.end)}`).join('，') }}</small></article></div><form class="question-form" @submit.prevent="ask"><label class="sr-only" for="ai-question">针对视频内容提问</label><input id="ai-question" v-model="question" :disabled="asking" maxlength="1000" placeholder="例如：这个视频最重要的结论是什么？"><button class="ai-primary" type="submit" :disabled="asking || !question.trim()"><LoaderCircle v-if="asking" class="spin" :size="16"/><Send v-else :size="16"/>发送</button></form><button v-if="answers.length" class="ai-link" type="button" @click="clearConversation">清空当前会话</button></template></template>
    </div>
  </section>
</template>

<style scoped>
.ai-workspace{max-width:1040px;margin:0 auto 42px;padding:30px;background:#fff;border:1px solid #dce6f7;border-radius:14px;box-shadow:0 12px 32px #263f6810}.ai-header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.ai-eyebrow{display:flex;align-items:center;gap:7px;color:#2563eb;font-weight:700;margin:0 0 8px}.ai-header h2{margin:0;font-size:24px}.ai-header p:not(.ai-eyebrow){color:#667085;margin:8px 0 0;line-height:1.6}.ai-controls{margin:24px 0 18px;padding:14px;background:#f6f9ff;border-radius:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}.ai-controls label{font-weight:700}.ai-controls select{min-height:42px;border:1px solid #bfceed;border-radius:7px;padding:0 10px;background:#fff;color:#24314a}.ai-primary,.ai-secondary,.ai-copy{min-height:42px;border:0;border-radius:7px;padding:0 15px;display:inline-flex;align-items:center;justify-content:center;gap:7px;font-weight:700}.ai-primary{background:#2563eb;color:#fff}.ai-primary:disabled,.ai-copy:disabled{opacity:.55;cursor:not-allowed}.ai-secondary,.ai-copy{background:#edf4ff;color:#245fc6;border:1px solid #c9dcff}.ai-copy{flex:none}.ai-status,.ai-empty{font-size:14px;color:#61718b;display:inline-flex;align-items:center;gap:5px}.ai-empty{color:#93620d}.ai-tabs{display:flex;gap:4px;border-bottom:1px solid #dce6f7;overflow:auto}.ai-tabs button{white-space:nowrap;border:0;border-bottom:3px solid transparent;background:transparent;padding:12px 15px;color:#667085;display:inline-flex;align-items:center;gap:6px}.ai-tabs button.active{color:#2563eb;border-bottom-color:#2563eb;font-weight:700}.ai-panel{padding-top:22px}.ai-loading,.ai-placeholder{min-height:170px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;color:#667085;text-align:center}.ai-loading strong{color:#24314a}.overview{border-left:4px solid #2563eb;background:#f6f9ff;padding:16px 18px;border-radius:0 9px 9px 0}.overview h3,.summary-grid h3{margin:0 0 9px;color:#1e293b}.overview p{margin:0;line-height:1.75}.summary-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}.summary-grid article{border:1px solid #e2e8f5;border-radius:10px;padding:16px}.summary-grid ol,.summary-grid ul{margin:0;padding-left:20px}.summary-grid li+li{margin-top:14px}.summary-grid p{margin:5px 0 0;color:#5d6b80;line-height:1.6}.keywords{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.keywords span{background:#edf4ff;color:#245fc6;border-radius:99px;padding:6px 11px;font-size:13px}.transcript-list{max-height:520px;overflow:auto;border:1px solid #e2e8f5;border-radius:9px}.cue{width:100%;border:0;border-bottom:1px solid #eef2f8;background:#fff;text-align:left;padding:12px 15px;display:grid;grid-template-columns:72px 1fr;gap:12px;color:#354258;line-height:1.6}.cue:hover{background:#f6f9ff}.cue time{color:#2563eb;font-variant-numeric:tabular-nums;font-weight:700}.mindmap-host{overflow:auto;min-height:240px;border:1px solid #e2e8f5;border-radius:9px;padding:16px;background:#fbfdff}.mindmap-host :deep(svg){min-width:620px;max-width:none}.mindmap-fallback{margin:14px 0;color:#536278}.mindmap-tree{line-height:1.8}.conversation{display:grid;gap:12px;max-height:410px;overflow:auto;margin-bottom:14px}.answer{padding:14px;border:1px solid #e2e8f5;border-radius:9px;line-height:1.65;color:#3b4960}.answer p{margin:0}.answer .question{font-weight:700;color:#1e3a70;margin-bottom:7px}.answer small{display:block;color:#667085;margin-top:9px}.question-form{display:flex;gap:10px}.question-form input{flex:1;min-width:0;min-height:44px;border:1px solid #bfcbe0;border-radius:7px;padding:0 12px}.ai-link{border:0;background:transparent;color:#5573a9;padding:10px 0;text-decoration:underline}.ai-error{color:#b42318;margin:12px 0}.spin{animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}@media(max-width:800px){.ai-workspace{margin:0 16px 28px;padding:20px}.ai-header{flex-direction:column}.ai-copy{width:100%}.summary-grid{grid-template-columns:1fr}.question-form{align-items:stretch}.question-form .ai-primary{padding:0 12px}.ai-tabs button{padding:12px}.ai-controls{align-items:stretch}.ai-controls select,.ai-controls .ai-primary{width:100%}}
.streamed-summary{max-height:360px;overflow:auto;white-space:pre-wrap;margin:0 0 16px;padding:16px;border:1px solid #c9dcff;border-radius:9px;background:#f8fbff;color:#26354d;line-height:1.7;text-align:left;font:14px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace}.mindmap-host :deep(svg){min-width:620px;min-height:280px}
</style>
