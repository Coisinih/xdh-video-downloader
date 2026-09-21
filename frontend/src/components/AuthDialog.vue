<script setup lang="ts">
import { ref } from 'vue'
import { LoaderCircle, LockKeyhole, X } from 'lucide-vue-next'
import { login, register, type CurrentUser } from '../api'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; authenticated: [user: CurrentUser] }>()
const mode = ref<'login' | 'register'>('login')
const email = ref('')
const password = ref('')
const pending = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  pending.value = true
  try {
    const user = mode.value === 'login' ? await login(email.value, password.value) : await register(email.value, password.value)
    emit('authenticated', user)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '登录失败，请稍后重试。'
  } finally { pending.value = false }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="auth-backdrop" role="presentation" @mousedown.self="emit('close')">
      <section class="auth-dialog" role="dialog" aria-modal="true" aria-labelledby="auth-title">
        <button class="auth-close" type="button" aria-label="关闭登录窗口" @click="emit('close')"><X :size="20" aria-hidden="true" /></button>
        <span class="auth-icon"><LockKeyhole :size="24" aria-hidden="true" /></span>
        <h2 id="auth-title">{{ mode === 'login' ? '登录 VidNest' : '创建账号' }}</h2>
        <p>{{ mode === 'login' ? '登录后可购买和管理会员。' : '使用邮箱和高强度密码创建账号。' }}</p>
        <form @submit.prevent="submit">
          <label for="auth-email">邮箱</label>
          <input id="auth-email" v-model.trim="email" type="email" autocomplete="email" required maxlength="254">
          <label for="auth-password">密码</label>
          <input id="auth-password" v-model="password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" required minlength="10" maxlength="128" aria-describedby="password-help">
          <small id="password-help">注册密码至少 10 位，且包含大小写字母、数字、符号中的三类。</small>
          <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
          <button class="auth-submit" type="submit" :disabled="pending"><LoaderCircle v-if="pending" class="spin" :size="17" aria-hidden="true" />{{ pending ? '处理中…' : (mode === 'login' ? '登录' : '注册并登录') }}</button>
        </form>
        <button class="auth-switch" type="button" @click="mode = mode === 'login' ? 'register' : 'login'; error = ''">{{ mode === 'login' ? '没有账号？立即注册' : '已有账号？返回登录' }}</button>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.auth-backdrop{position:fixed;z-index:1100;inset:0;display:grid;place-items:center;padding:20px;background:#17213ab8}.auth-dialog{position:relative;width:min(440px,100%);padding:34px;border-radius:20px;background:#fff;box-shadow:0 24px 70px #0f172a50}.auth-close{position:absolute;top:15px;right:15px;width:42px;height:42px;display:grid;place-items:center;border:0;border-radius:50%;background:#f1f5f9;color:#475569}.auth-icon{width:50px;height:50px;display:grid;place-items:center;border-radius:15px;background:#edf4ff;color:#2563eb}.auth-dialog h2{margin:18px 0 7px;color:#17213a;font-size:28px}.auth-dialog>p{margin:0 0 22px;color:#64748b}.auth-dialog form{display:grid;gap:8px}.auth-dialog label{margin-top:8px;color:#334155;font-weight:700}.auth-dialog input{width:100%;height:48px;border:1px solid #cbd5e1;border-radius:9px;padding:0 13px;font-size:16px}.auth-dialog small{color:#718096;line-height:1.5}.auth-error{margin:8px 0 0!important;color:#b42318!important;font-size:14px}.auth-submit{min-height:50px;margin-top:12px;border:0;border-radius:9px;background:#3478f6;color:#fff;font-weight:800;display:flex;align-items:center;justify-content:center;gap:7px}.auth-submit:disabled{opacity:.6}.auth-switch{width:100%;margin-top:18px;border:0;background:transparent;color:#2563eb;font-weight:700}.spin{animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
</style>
