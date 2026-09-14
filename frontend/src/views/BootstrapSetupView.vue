<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import { bootstrapAdmin, getBootstrapStatus } from '../api/bootstrap'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()
const formRef = ref()
const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const form = reactive({ username: '', password: '', password_confirm: '' })

const rules = {
  username: [
    { required: true, message: '请输入管理员账号', trigger: 'blur' },
    { min: 3, max: 150, message: '账号长度应为 3 到 150 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入管理员密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 个字符', trigger: 'blur' },
  ],
  password_confirm: [
    { required: true, message: '请再次输入管理员密码', trigger: 'blur' },
    { validator: (_rule, value, callback) => value === form.password ? callback() : callback(new Error('两次输入的密码不一致')), trigger: 'blur' },
  ],
}

function errorMessage(errorResponse) {
  const data = errorResponse.response?.data
  if (data && typeof data === 'object') {
    const first = Object.values(data)[0]
    return Array.isArray(first) ? first[0] : String(first)
  }
  return '初始化失败，请稍后重试。'
}

async function loadStatus() {
  try {
    const status = await getBootstrapStatus()
    if (!status.setup_required) {
      await router.replace('/login')
      return
    }
  } catch (statusError) {
    error.value = errorMessage(statusError)
  } finally {
    loading.value = false
  }
}

async function submit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  error.value = ''
  try {
    await bootstrapAdmin(form)
    await userStore.login({ account: form.username, password: form.password })
    ElMessage.success('管理员账号已创建，正在进入工作台')
    await router.replace('/workspace')
  } catch (submitError) {
    error.value = errorMessage(submitError)
  } finally {
    submitting.value = false
  }
}

onMounted(loadStatus)
</script>

<template>
  <main class="auth-page bootstrap-page">
    <section class="setup-brand" aria-label="首次安装说明">
      <div class="setup-brand__mark"><span></span><span></span><span></span></div>
      <p class="setup-brand__eyebrow">FIRST-RUN SETUP</p>
      <h1>先创建管理员，<em>再开始使用。</em></h1>
      <p>这是本次部署的首次初始化。你将设置自己的平台管理员账号和密码，系统不会使用固定默认密码。</p>
      <div class="setup-brand__steps">
        <span><b>01</b>设置管理员账号</span>
        <span><b>02</b>进入平台工作台</span>
        <span><b>03</b>邀请成员并分配权限</span>
      </div>
    </section>

    <section class="auth-form-panel">
      <div class="auth-form-wrap">
        <div class="auth-heading">
          <span class="auth-heading__index">ACCOUNT / INITIALIZE</span>
          <h2>初始化平台</h2>
          <p>创建首个管理员账号。初始化完成后，此页面将自动关闭。</p>
        </div>
        <div v-if="loading" class="setup-loading">正在检查平台初始化状态…</div>
        <el-form v-else ref="formRef" :model="form" :rules="rules" label-position="top" class="auth-form auth-form--compact">
          <el-form-item label="管理员账号" prop="username"><el-input v-model="form.username" size="large" placeholder="例如：platform_admin" autocomplete="username" /></el-form-item>
          <el-form-item label="管理员密码" prop="password"><el-input v-model="form.password" type="password" show-password size="large" placeholder="至少 8 个字符" autocomplete="new-password" /></el-form-item>
          <el-form-item label="确认密码" prop="password_confirm"><el-input v-model="form.password_confirm" type="password" show-password size="large" placeholder="再次输入密码" autocomplete="new-password" /></el-form-item>
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>
          <button class="tech-button" type="button" :disabled="submitting" @click="submit">
            <span>{{ submitting ? '正在创建…' : '创建管理员并进入平台' }}</span><b>→</b>
          </button>
        </el-form>
        <p class="auth-security"><span>◆</span> 密码只保存为不可逆摘要，不会显示给其他用户</p>
      </div>
    </section>
  </main>
</template>
