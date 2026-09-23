<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Check, Crown, Download, Flame, Headphones, LoaderCircle, RefreshCw, Send } from 'lucide-vue-next'
import { createBatchDownload, createBillingPortal, createCheckout, createSupportTicket, getBatchDownload, getBillingStatus, getCurrentUser, type BatchTask, type BillingStatus, type CurrentUser } from '../api'

const props = defineProps<{ user: CurrentUser | null }>()
const emit = defineEmits<{ login: []; refreshed: [user: CurrentUser] }>()
const autoRenew = ref(false)
const paying = ref(false)
const managing = ref(false)
const message = ref('')
const error = ref('')
const billing = ref<BillingStatus | null>(null)
const batchUrls = ref('')
const batch = ref<BatchTask | null>(null)
const batchPending = ref(false)
const supportSubject = ref('')
const supportMessage = ref('')
const supportPending = ref(false)

const isVip = computed(() => props.user?.membership.is_vip === true)
const expiry = computed(() => props.user?.membership.expires_at ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'long', timeStyle: 'short' }).format(new Date(props.user.membership.expires_at)) : '')

async function loadBilling() {
  if (!props.user) { billing.value = null; return }
  try { billing.value = await getBillingStatus() } catch { billing.value = null }
}

async function buy() {
  if (!props.user) { emit('login'); return }
  error.value = ''; message.value = ''; paying.value = true
  try {
    const result = await createCheckout(autoRenew.value ? 'subscription' : 'one_time')
    window.location.assign(result.checkout_url)
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '无法创建支付页面。'; paying.value = false }
}

async function portal() {
  managing.value = true; error.value = ''
  try { window.location.assign((await createBillingPortal()).url) }
  catch (caught) { error.value = caught instanceof Error ? caught.message : '无法打开会员管理页面。'; managing.value = false }
}

async function startBatch() {
  const urls = batchUrls.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean)
  if (!urls.length) { error.value = '请至少输入一个视频链接。'; return }
  batchPending.value = true; error.value = ''
  try {
    batch.value = await createBatchDownload(urls)
    while (batch.value.status !== 'completed') {
      await new Promise(resolve => window.setTimeout(resolve, 1200))
      batch.value = await getBatchDownload(batch.value.id)
    }
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '批量下载任务创建失败。' }
  finally { batchPending.value = false }
}

async function sendSupport() {
  supportPending.value = true; error.value = ''
  try {
    const result = await createSupportTicket(supportSubject.value, supportMessage.value)
    message.value = `工单 ${result.id} 已提交，客服处理时会通过注册邮箱联系你。`
    supportSubject.value = ''; supportMessage.value = ''
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '客服工单提交失败。' }
  finally { supportPending.value = false }
}

async function handlePaymentReturn() {
  if (!props.user || typeof window === 'undefined') return
  const params = new URLSearchParams(window.location.search)
  const payment = params.get('payment')
  if (payment === 'cancelled') message.value = '你已取消支付，订单不会开通会员。'
  if (payment === 'success') {
    message.value = 'Stripe 已受理支付，正在等待安全确认…'
    for (let attempt = 0; attempt < 12; attempt += 1) {
      try {
        const user = await getCurrentUser()
        emit('refreshed', user)
        if (user.membership.is_vip) { message.value = '支付已确认，VIP 权益已经生效。'; break }
      } catch { /* Retry while the webhook is being forwarded. */ }
      await new Promise(resolve => window.setTimeout(resolve, 1500))
    }
  }
  if (payment) window.history.replaceState({}, '', `${window.location.pathname}${window.location.hash || '#pricing'}`)
}

watch(() => props.user?.id, async () => { await loadBilling(); await handlePaymentReturn() })
onMounted(async () => { await loadBilling(); await handlePaymentReturn() })
</script>

<template>
  <section id="pricing" class="membership-section" aria-labelledby="pricing-title">
    <header class="membership-heading">
      <p>简单透明的会员方案</p>
      <h2 id="pricing-title">选择适合你的视频下载方案</h2>
      <span>免费版满足日常下载与 AI 试用，VIP 解锁高画质、批量下载与不限次数 AI</span>
    </header>
    <p v-if="message" class="membership-message" role="status">{{ message }}</p>
    <p v-if="error" class="membership-error" role="alert">{{ error }}</p>
    <div class="pricing-grid">
      <article class="pricing-card free-card">
        <h3>免费版</h3><p>登录后即可不限次数下载</p><strong class="price">¥0 <small>/永久</small></strong>
        <ul><li><Check :size="18" />未登录每日 5 次免费下载</li><li><Check :size="18" />登录后不限次数下载</li><li><Check :size="18" />每日 3 次 AI 总结</li><li><Check :size="18" />最高支持 720P 清晰度</li></ul>
        <button type="button" disabled>{{ isVip ? 'VIP 已生效' : '当前方案' }}</button>
      </article>
      <article class="pricing-card vip-card">
        <span class="recommended"><Flame :size="14" />推荐</span>
        <h3>VIP 高级版</h3><p>解锁全部功能，无限制使用</p><strong class="price">¥9.9 <small>/ {{ autoRenew ? '月' : '30 天' }}</small></strong>
        <label class="renew-option"><input v-model="autoRenew" type="checkbox" :disabled="isVip"><span>自动续费（月度订阅，可随时取消）</span></label>
        <ul><li><Check :size="18" />AI 总结与视频问答不限次数</li><li><Check :size="18" />最高支持 4K / 8K 画质</li><li><Check :size="18" />批量下载，一键创建任务</li><li><Check :size="18" />字幕下载与 DeepSeek 翻译</li><li><Check :size="18" />专属客服工单支持</li></ul>
        <button v-if="!isVip" type="button" :disabled="paying" @click="buy"><LoaderCircle v-if="paying" class="spin" :size="17" /><Crown v-else :size="17" />{{ paying ? '正在前往 Stripe…' : '立即开通 VIP' }}</button>
        <button v-else-if="user?.membership.source === 'subscription'" class="active-vip" type="button" :disabled="managing" @click="portal"><RefreshCw :size="17" />{{ managing ? '正在打开…' : '管理会员与自动续费' }}</button>
        <button v-else class="active-vip" type="button" disabled><Crown :size="17" />30 天 VIP 已生效</button>
      </article>
    </div>
    <section v-if="isVip" class="vip-tools" aria-label="VIP 专属工具">
      <header><div><p>VIP 工作台</p><h3>批量下载与专属支持</h3></div><span>会员有效期至 {{ expiry }}</span></header>
      <div class="vip-tool-grid">
        <form @submit.prevent="startBatch"><h4><Download :size="18" />批量下载</h4><label for="batch-urls">每行粘贴一个公开视频链接，单次最多 10 个</label><textarea id="batch-urls" v-model="batchUrls" rows="5" required></textarea><button type="submit" :disabled="batchPending"><LoaderCircle v-if="batchPending" class="spin" :size="16" />{{ batchPending ? '任务处理中…' : '一键创建下载任务' }}</button></form>
        <form @submit.prevent="sendSupport"><h4><Headphones :size="18" />专属客服</h4><label for="support-subject">问题主题</label><input id="support-subject" v-model="supportSubject" required minlength="2" maxlength="120"><label for="support-message">问题描述</label><textarea id="support-message" v-model="supportMessage" rows="3" required minlength="10" maxlength="4000"></textarea><button type="submit" :disabled="supportPending"><Send :size="16" />提交客服工单</button></form>
      </div>
      <div v-if="batch" class="batch-results" aria-live="polite"><article v-for="item in batch.items" :key="item.url"><div><strong>{{ item.title || item.url }}</strong><span>{{ item.error || `${item.status} · ${Math.round(item.progress)}%` }}</span></div><a v-if="item.delivery_url" :href="item.delivery_url" download>下载文件</a></article></div>
    </section>
  </section>
</template>

<style scoped>
.membership-section{max-width:1180px;margin:0 auto;padding:76px 24px}.membership-heading{text-align:center}.membership-heading>p{margin:0 0 10px;color:#3478f6;font-weight:800}.membership-heading h2{margin:0;color:#17213a;font-size:clamp(30px,4vw,48px)}.membership-heading span{display:block;margin-top:12px;color:#718096;font-size:17px}.membership-message,.membership-error{max-width:820px;margin:22px auto 0;padding:12px 16px;border-radius:9px;text-align:center}.membership-message{background:#ecfdf5;color:#047857}.membership-error{background:#fef2f2;color:#b42318}.pricing-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px;margin-top:42px}.pricing-card{position:relative;display:flex;flex-direction:column;min-height:520px;padding:34px;border:1px solid #e1e7ef;border-radius:20px;background:#fff}.pricing-card h3{margin:0;color:#17213a;font-size:23px}.pricing-card>p{margin:8px 0 22px;color:#718096}.price{font-size:40px;color:#17213a;font-variant-numeric:tabular-nums}.price small{font-size:15px;color:#94a3b8}.pricing-card ul{display:grid;gap:14px;margin:25px 0 32px;padding:0;list-style:none}.pricing-card li{display:flex;align-items:center;gap:10px;color:#536278}.pricing-card li svg{flex:none;color:#39b77c}.pricing-card>button,.vip-tools form button{min-height:48px;margin-top:auto;border:0;border-radius:999px;font-weight:800;display:flex;align-items:center;justify-content:center;gap:7px}.free-card>button{border:1px solid #dbe2ea;background:#fff;color:#64748b}.vip-card{overflow:hidden;border:0;background:linear-gradient(145deg,#4080f8,#2463e9);box-shadow:0 22px 45px #2563eb30}.vip-card h3,.vip-card .price{color:#fff}.vip-card>p,.vip-card .price small,.vip-card li{color:#e7efff}.vip-card li svg{color:#ffe865}.vip-card>button{background:#fff;color:#2463e9}.recommended{position:absolute;top:18px;right:18px;padding:7px 12px;border-radius:999px;background:#ffffff26;color:#fff;display:flex;align-items:center;gap:5px;font-size:13px}.renew-option{display:flex;align-items:center;gap:10px;margin:18px 0 0;padding:12px;border-radius:10px;background:#ffffff18;color:#fff;cursor:pointer}.renew-option input{width:18px;height:18px}.active-vip{border:1px solid #fff!important}.vip-tools{margin-top:28px;padding:30px;border:1px solid #dce7f9;border-radius:20px;background:#fff}.vip-tools>header{display:flex;justify-content:space-between;gap:20px;align-items:end}.vip-tools header p{margin:0;color:#3478f6;font-weight:800}.vip-tools header h3{margin:5px 0 0;font-size:26px}.vip-tools header span{color:#64748b}.vip-tool-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:24px}.vip-tools form{display:flex;flex-direction:column;gap:8px;padding:20px;border-radius:14px;background:#f8fbff}.vip-tools h4{display:flex;align-items:center;gap:7px;margin:0 0 6px;font-size:18px}.vip-tools label{color:#536278;font-size:13px}.vip-tools input,.vip-tools textarea{width:100%;border:1px solid #cbd5e1;border-radius:8px;padding:10px;background:#fff;resize:vertical}.vip-tools form button{margin-top:8px;border-radius:8px;background:#3478f6;color:#fff}.batch-results{display:grid;gap:8px;margin-top:20px}.batch-results article{display:flex;justify-content:space-between;gap:18px;padding:13px;border:1px solid #e2e8f0;border-radius:9px}.batch-results article div{display:grid;min-width:0}.batch-results strong{overflow-wrap:anywhere}.batch-results span{color:#64748b;font-size:13px}.batch-results a{flex:none;color:#2563eb;font-weight:800}.spin{animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:760px){.pricing-grid,.vip-tool-grid{grid-template-columns:1fr}.membership-section{padding:56px 16px}.pricing-card{min-height:0;padding:26px}.vip-tools{padding:20px}.vip-tools>header{align-items:start;flex-direction:column}}
</style>
