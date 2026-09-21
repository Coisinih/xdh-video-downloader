<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowDownToLine, CheckCircle2, Clipboard, Crown, Download, Eye, FileVideo, Globe2, Link, LoaderCircle, LogIn, LogOut, ShieldCheck, UserRound } from 'lucide-vue-next'
import { createDownload, getCurrentUser, getDownload, inspect, logout, type CurrentUser, type Format, type Inspection } from './api'
import AiLearningWorkspace from './components/AiLearningWorkspace.vue'
import AuthDialog from './components/AuthDialog.vue'
import MembershipCenter from './components/MembershipCenter.vue'
import SeoContent from './components/SeoContent.vue'

const url = ref('')
const inspection = ref<Inspection | null>(null)
const selectedFormat = ref<Format | null>(null)
const pending = ref(false)
const error = ref('')
const thumbnailFailed = ref(false)
const user = ref<CurrentUser | null>(null)
const authOpen = ref(false)

const duration = computed(() => inspection.value?.duration ? `${Math.floor(inspection.value.duration / 60)}:${String(inspection.value.duration % 60).padStart(2, '0')}` : '时长未知')
const platform = computed(() => inspection.value?.platform || '未知平台')
const views = computed(() => inspection.value?.view_count === undefined ? '暂无播放数据' : new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(inspection.value.view_count))
const avatarInitial = computed(() => user.value?.email?.trim().charAt(0).toUpperCase() || 'U')
const size = (bytes?: number) => !bytes ? '大小待定' : `${(bytes / 1024 / 1024).toFixed(1)} MB`
const quality = (format: Format) => {
  const labels: Record<string, string> = {
    '1080': '1080p 高清',
    '720': '720p 准高清',
    '480': '480p 标清',
    '360': '360p 流畅',
    '1440': '2K 超清',
    '2160': '4K 超清',
    '4320': '8K 极清',
  }
  const height = String(format.resolution || format.label).match(/(1080|720|480|360)/)?.[1]
  return (height && labels[height]) || `${format.label.toLowerCase()} 清晰度`
}

async function refreshUser() {
  try { user.value = await getCurrentUser() } catch { user.value = null }
}

async function signOut() {
  try { await logout() } finally { user.value = null; inspection.value = null }
}

function authenticated(value: CurrentUser) { user.value = value; authOpen.value = false }

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
    let deliveryUrl = result.delivery_url
    if (!deliveryUrl && result.task_id) {
      for (let attempt = 0; attempt < 900; attempt += 1) {
        await new Promise(resolve => window.setTimeout(resolve, 1000))
        const task = await getDownload(result.task_id)
        if (task.status === 'failed') throw new Error(task.error || '服务端合并下载失败。')
        if (task.status === 'completed') { deliveryUrl = task.delivery_url; break }
      }
    }
    if (!deliveryUrl) throw new Error('服务端合并下载超时，请稍后重试。')
    const frame = document.createElement('iframe')
    frame.hidden = true
    frame.src = deliveryUrl
    document.body.appendChild(frame)
    window.setTimeout(() => frame.remove(), 60000)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '创建下载失败。'
  } finally {
    pending.value = false
  }
}

onMounted(refreshUser)
</script>

<template>
  <a class="skip-link" href="#main-content">跳到主要内容</a>
  <main id="main-content" :class="{ 'has-result': inspection }">
    <header class="site-header">
      <a class="brand" href="#main-content" aria-label="VidNest 首页"><span class="brand-mark"><ArrowDownToLine :size="22" aria-hidden="true" /></span><strong>VidNest</strong><span class="brand-tag">视频下载总结器</span></a>
      <nav aria-label="主导航"><a href="#features">核心功能</a><a href="#pricing">会员方案</a><a href="#how-it-works">使用方法</a><a href="#platforms">支持平台</a></nav>
      <div class="account-actions"><a v-if="user?.membership.is_vip" class="vip-status" href="#pricing"><Crown :size="16" />VIP</a><div v-if="user" class="account-menu"><button class="avatar-button" type="button" :aria-label="`账号菜单：${user.email}`"><span aria-hidden="true">{{ avatarInitial }}</span></button><div class="account-dropdown"><div class="account-card"><p class="account-email">{{ user.email }}</p><button class="header-action" type="button" @click="signOut"><LogOut :size="16" />退出登录</button></div></div></div><button v-else class="header-action" type="button" @click="authOpen = true"><LogIn :size="16" />登录 / 注册</button></div>
    </header>

    <section class="hero" aria-label="视频下载与总结">
      <p class="trust"><i></i> 面向公开、无 DRM、无需登录的视频内容</p>
      <h1>万能视频下载与 <em>AI 视频总结</em></h1>
      <p class="lead">VidNest 可解析公开视频链接、选择清晰度并下载；视频带有可用字幕时，还能生成视频大纲、字幕文本、思维导图和基于字幕证据的 AI 问答。</p>
      <section class="workbench" aria-label="视频下载器">
        <label class="sr-only" for="source-url">公开视频链接</label>
        <div class="url-row">
          <Link :size="22" />
          <input id="source-url" v-model="url" type="url" placeholder="粘贴视频链接，例如 https://..." @keyup.enter="parse" />
          <button class="primary" type="button" :disabled="pending" @click="parse"><LoaderCircle v-if="pending" class="spin" :size="18" /><span v-else><Download :size="18" />解析视频</span></button>
        </div>
        <div class="examples"><span>试试：</span><button type="button" @click="url = 'https://www.bilibili.com/video/BV1DAgS6SEqa'">B 站</button><button type="button" @click="url = 'https://www.acfun.cn/v/ac35457073'">AcFun</button><button type="button" @click="url = 'https://www.huya.com/video/play/1002412640.html'">虎牙</button><button class="paste-link" type="button" @click="paste"><Clipboard :size="14" />粘贴链接</button></div>
      </section>
      <p class="helper"><ShieldCheck :size="15" /> 仅下载你有权保存且无需登录的公开内容。</p>
      <p v-if="user && !user.membership.is_vip" class="quota-note">今日还可免费下载 {{ user.remaining_free_downloads }} 次，最高 720P。</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </section>

    <section v-if="inspection" class="result-workspace" aria-live="polite">
      <section class="result video-info" aria-label="视频信息与下载">
        <div class="video-head">
          <div class="video-media">
            <img v-if="inspection.thumbnail && !thumbnailFailed" :src="`/api/v1/thumbnails/${inspection.inspection_id}`" :alt="`${inspection.title} 视频封面`" width="640" height="360" @error="thumbnailFailed = true" />
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

      <AiLearningWorkspace v-if="user?.membership.is_vip" :inspection="inspection" />
      <section v-else class="ai-vip-lock" aria-label="VIP AI 功能"><Crown :size="28" aria-hidden="true" /><h2>开通 VIP 解锁 AI 视频学习助手</h2><p>包含字幕下载与翻译、视频大纲、思维导图和字幕证据问答。</p><a href="#pricing">查看会员方案</a></section>
    </section>

    <MembershipCenter :user="user" @login="authOpen = true" @refreshed="user = $event" />
    <SeoContent />

    <footer><span>© 2026 VidNest · 开发者：咸蛋黄</span><a href="mailto:senwei0521@gmail.com">senwei0521@gmail.com</a><span>公开视频下载 · 字幕提取 · AI 视频总结</span></footer>
  </main>
  <AuthDialog :open="authOpen" @close="authOpen = false" @authenticated="authenticated" />
</template>
