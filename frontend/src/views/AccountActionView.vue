<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import AuthBrandPanel from '../components/auth/AuthBrandPanel.vue'
import { activateAccount, resetAccountPassword } from '../api/accountActions'

const route = useRoute()
const router = useRouter()
const formRef = ref()
const busy = ref(false)
const completed = ref(false)
const error = ref('')
const form = reactive({ password: '', password_confirm: '' })
const isReset = computed(() => route.name === 'password-reset')
const token = computed(() => String(route.query.token || ''))
const title = computed(() => isReset.value ? '重置账号密码' : '激活平台账号')
const description = computed(() => isReset.value ? '请设置新的登录密码，完成后返回登录页面。' : '请设置登录密码，激活后使用自己的账号进入平台。')

const rules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 个字符', trigger: 'blur' },
  ],
  password_confirm: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    { validator: (_rule, value, callback) => value === form.password ? callback() : callback(new Error('两次输入的密码不一致')), trigger: 'blur' },
  ],
}

function errorMessage(err) {
  const data = err.response?.data
  if (data && typeof data === 'object') {
    const first = Object.values(data)[0]
    return Array.isArray(first) ? first[0] : String(first)
  }
  return '操作失败，请稍后重试。'
}

async function submit() {
  if (!token.value) {
    error.value = '链接缺少一次性令牌，请让管理员重新生成链接。'
    return
  }
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  busy.value = true
  error.value = ''
  try {
    const action = isReset.value ? resetAccountPassword : activateAccount
    await action({ token: token.value, password: form.password, password_confirm: form.password_confirm })
    completed.value = true
    ElMessage.success(isReset.value ? '密码已重置' : '账号已激活')
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <AuthBrandPanel eyebrow="SECURE ACCOUNT ACTION" />
    <section class="auth-form-panel auth-form-panel--register">
      <div class="auth-form-wrap">
        <div class="mobile-brand"><span class="brand-dot"></span> AITS</div>
        <div class="auth-heading">
          <span class="auth-heading__index">ACCOUNT / SECURITY</span>
          <h2>{{ title }}</h2>
          <p>{{ completed ? (isReset ? '密码已更新，请返回登录。' : '账号已激活，请使用自己的账号登录。') : description }}</p>
        </div>
        <template v-if="completed">
          <button class="tech-button" type="button" @click="router.push('/login')"><span>返回登录</span><b>→</b></button>
        </template>
        <el-form v-else ref="formRef" :model="form" :rules="rules" label-position="top" class="auth-form auth-form--compact">
          <el-form-item label="新密码" prop="password"><el-input v-model="form.password" type="password" show-password size="large" placeholder="至少 8 个字符" autocomplete="new-password" /></el-form-item>
          <el-form-item label="确认密码" prop="password_confirm"><el-input v-model="form.password_confirm" type="password" show-password size="large" placeholder="再次输入密码" autocomplete="new-password" /></el-form-item>
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>
          <button class="tech-button" type="button" :disabled="busy" @click="submit"><span>{{ busy ? '处理中...' : (isReset ? '确认重置密码' : '激活账号') }}</span><b>→</b></button>
        </el-form>
        <p v-if="!completed" class="auth-switch"><RouterLink to="/login">返回登录</RouterLink></p>
      </div>
    </section>
  </main>
</template>
