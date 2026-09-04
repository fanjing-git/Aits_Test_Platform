<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import AuthBrandPanel from '../components/auth/AuthBrandPanel.vue'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()
const formRef = ref()
const showPassword = ref(false)
const form = reactive({ account: '', password: '' })
const rules = {
  account: [{ required: true, message: '请输入用户名或邮箱', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

function getErrorMessage(error) {
  if (error.response?.status === 401) return '用户名或密码不正确'
  return error.response?.data?.detail || '登录失败，请稍后重试'
}

async function submit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  try {
    await userStore.login(form)
    ElMessage.success('欢迎回来')
    await router.push('/workspace')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}
</script>

<template>
  <main class="auth-page">
    <AuthBrandPanel />
    <section class="auth-form-panel">
      <div class="auth-form-wrap">
        <div class="mobile-brand"><span class="brand-dot"></span> AITS</div>
        <div class="auth-heading">
          <span class="auth-heading__index">01 / ACCESS</span>
          <h2>欢迎登录</h2>
          <p>进入 AI 智能体测试工作空间</p>
        </div>
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="auth-form" @keyup.enter="submit">
          <el-form-item label="用户名或邮箱" prop="account">
            <el-input v-model="form.account" size="large" placeholder="请输入用户名或邮箱" autocomplete="username">
              <template #prefix><span class="field-icon">⌁</span></template>
            </el-input>
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input v-model="form.password" :type="showPassword ? 'text' : 'password'" size="large" placeholder="请输入密码" autocomplete="current-password">
              <template #prefix><span class="field-icon">◇</span></template>
              <template #suffix><button type="button" class="password-toggle" @click="showPassword = !showPassword">{{ showPassword ? '隐藏' : '显示' }}</button></template>
            </el-input>
          </el-form-item>
          <button class="tech-button" type="button" :disabled="userStore.loading" @click="submit">
            <span>{{ userStore.loading ? '身份验证中...' : '进入工作空间' }}</span><b>→</b>
          </button>
        </el-form>
        <p class="auth-switch">还没有账号？<RouterLink to="/register">创建平台账号</RouterLink></p>
        <p class="auth-security"><span>◆</span> 通信已加密 · JWT 安全认证</p>
      </div>
    </section>
  </main>
</template>
