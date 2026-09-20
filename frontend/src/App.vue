<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowDownToLine, CheckCircle2, Clipboard, Download, Eye, FileVideo, Globe2, Link, LoaderCircle, ShieldCheck, Sparkles, UserRound } from 'lucide-vue-next'
import { createDownload, inspect, type Format, type Inspection } from './api'
import AiLearningWorkspace from './components/AiLearningWorkspace.vue'

const url = ref('')
const inspection = ref<Inspection | null>(null)
const selectedFormat = ref<Format | null>(null)
const pending = ref(false)
const error = ref('')
const thumbnailFailed = ref(false)

const duration = computed(() => inspection.value?.duration ? `${Math.floor(inspection.value.duration / 60)}:${String(inspection.value.duration % 60).padStart(2, '0')}` : '时长未知')
const platform = computed(() => inspection.value?.platform || '未知平台')
const views = computed(() => inspection.value?.view_count === undefined ? '暂无播放数据' : new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(inspection.value.view_count))
const size = (bytes?: number) => !bytes ? '大小待定' : `${(bytes / 1024 / 1024).toFixed(1)} MB`
const quality = (format: Format) => {
  const labels: Record<string, string> = {
    '1080': '1080p 高清',
    '720': '720p 准高清',
    '480': '480p 标清',
    '360': '360p 流畅',
  }
  const height = String(format.resolution || format.label).match(/(1080|720|480|360)/)?.[1]
  return (height && labels[height]) || `${format.label.toLowerCase()} 清晰度`
}

async function paste() {
  try { url.value = await navigator.clipboard.readText() } catch { error.value = '无法读取剪贴板，请手动粘贴链接。' }
}

async function parse() {
  error.value = ''
  inspection.value = null
  selectedFormat.value = null
  thumbnailFailed.value = false
  if (!url.value.trim()) { error.value = '请输入公开视频链接。'; return }
  pending.value = true
  try {
    inspection.value = await inspect(url.value)
    selectedFormat.value = inspection.value.formats[0]
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '视频解析失败。'
  } finally {
    pending.value = false
  }
}

async function startDownload() {
  if (!inspection.value || !selectedFormat.value) return
  error.value = ''
  pending.value = true
  try {
    const result = await createDownload(inspection.value.inspection_id, selectedFormat.value.id)
    if (!result.delivery_url) throw new Error('无法创建下载链接。')
    const frame = document.createElement('iframe')
    frame.hidden = true
    frame.src = result.delivery_url
    document.body.appendChild(frame)
    window.setTimeout(() => frame.remove(), 60000)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '创建下载失败。'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <main :class="{ 'has-result': inspection }">
    <header class="site-header">
      <a class="brand" href="#" aria-label="VidNest 首页"><span class="brand-mark"><ArrowDownToLine :size="22" /></span><strong>VidNest</strong><span class="brand-tag">万能视频下载</span></a>
      <nav aria-label="主导航"><a href="#features">功能特性</a><a href="#pricing">套餐价格</a><a href="#platforms">支持平台</a></nav>
      <button class="vip-button" type="button"><Sparkles :size="18" />开通 VIP</button>
    </header>

    <section class="hero" aria-label="视频下载">
      <p class="trust"><i></i> 支持多个平台，免费使用</p>
      <h1>万能视频下载器，<em>一键保存</em></h1>
      <p class="lead">粘贴视频链接，智能解析，支持多种清晰度下载。已验证支持 B 站、AcFun 和虎牙公开视频。</p>
      <section class="workbench" aria-label="视频下载器">
        <label class="sr-only" for="source-url">公开视频链接</label>
        <div class="url-row">
          <Link :size="22" />
          <input id="source-url" v-model="url" type="url" placeholder="粘贴视频链接，例如 https://..." @keyup.enter="parse" />
          <button class="primary" type="button" :disabled="pending" @click="parse"><LoaderCircle v-if="pending" class="spin" :size="18" /><span v-else><Download :size="18" />解析视频</span></button>
        </div>
        <div class="examples"><span>试试：</span><button type="button" @click="url = 'https://www.bilibili.com/video/BV1xx411c7mD'">B 站</button><button type="button" @click="url = 'https://www.acfun.cn/v/ac35457073'">AcFun</button><button type="button" @click="url = 'https://www.huya.com/video/play/1002412640.html'">虎牙</button><button class="paste-link" type="button" @click="paste"><Clipboard :size="14" />粘贴链接</button></div>
      </section>
      <p class="helper"><ShieldCheck :size="15" /> 仅下载你有权保存且无需登录的公开内容。</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </section>

    <section v-if="inspection" class="result-workspace" aria-live="polite">
      <section class="result video-info" aria-label="视频信息与下载">
        <div class="video-head">
          <div class="video-media">
            <img v-if="inspection.thumbnail && !thumbnailFailed" :src="`/api/v1/thumbnails/${inspection.inspection_id}`" alt="视频封面" @error="thumbnailFailed = true" />
            <div v-else class="thumbnail"><FileVideo :size="30" /></div>
            <span class="video-duration">{{ duration }}</span>
          </div>
          <div>
            <h2>{{ inspection.title }}</h2>
          </div>
        </div>

        <dl class="video-metadata">
          <div class="metadata-author"><dt><UserRound :size="14" /><span class="sr-only">作者</span></dt><dd>{{ inspection.author || '暂无作者信息' }}</dd></div>
          <div class="metadata-platform"><dt><Globe2 :size="13" /><span class="sr-only">平台</span></dt><dd>{{ platform }}</dd></div>
          <div><dt><Eye :size="14" /><span class="sr-only">播放量</span></dt><dd>{{ views }}</dd></div>
        </dl>

        <section class="video-description" aria-label="视频简介">
          <span>{{ inspection.description || '暂无视频简介。' }}</span>
        </section>

        <fieldset>
          <legend>选择视频清晰度</legend>
          <div class="formats">
            <button v-for="format in inspection.formats" :key="format.id" type="button" class="format" :class="{ selected: selectedFormat?.id === format.id }" @click="selectedFormat = format">
              <strong>{{ quality(format) }}</strong>
              <span>{{ format.ext.toUpperCase() }} · {{ size(format.filesize) }}</span>
              <CheckCircle2 v-if="selectedFormat?.id === format.id" :size="17" />
            </button>
          </div>
        </fieldset>
        <button class="primary download" type="button" :disabled="pending" @click="startDownload"><Download :size="18" />浏览器下载</button>
      </section>

      <AiLearningWorkspace :inspection="inspection" />
    </section>

    <footer><span>VidNest MVP</span><span>浏览器直接下载 · 无需账号</span></footer>
  </main>
</template>
