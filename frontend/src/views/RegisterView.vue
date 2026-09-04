<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import AuthBrandPanel from '../components/auth/AuthBrandPanel.vue'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()
const formRef = ref()
const form = reactive({ account: '', password: '', password_confirm: '' })
const validateConfirmation = (_rule, value, callback) => {
  if (value !== form.password) callback(new Error('两次输入的密码不一致'))
  else callback()
}
const rules = {
  account: [
    { required: true, message: '请输入用户名或邮箱', trigger: 'blur' },
    { min: 3, max: 150, message: '账号长度为 3–150 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 个字符', trigger: 'blur' },
  ],
  password_confirm: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    { validator: validateConfirmation, trigger: 'blur' },
  ],
}

function getErrorMessage(error) {
  const data = error.response?.data
  if (data && typeof data === 'object') {
    const firstValue = Object.values(data)[0]
    return Array.isArray(firstValue) ? firstValue[0] : String(firstValue)
  }
  return '注册失败，请稍后重试'
}

async function submit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  try {
    await userStore.register(form)
    ElMessage.success('账号创建成功')
    await router.push('/workspace')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}
</script>

<template>
  <main class="auth-page">
    <AuthBrandPanel eyebrow="BUILD YOUR QUALITY INTELLIGENCE" />
    <section class="auth-form-panel auth-form-panel--register">
      <div class="auth-form-wrap">
        <div class="mobile-brand"><span class="brand-dot"></span> AITS</div>
        <div class="auth-heading">
          <span class="auth-heading__index">02 / CREATE ID</span>
          <h2>创建账号</h2>
          <p>开启你的智能质量工程工作空间</p>
        </div>
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="auth-form auth-form--compact">
          <el-form-item label="用户名或邮箱" prop="account"><el-input v-model="form.account" size="large" placeholder="任选一种方式注册" autocomplete="username" /></el-form-item>
          <el-form-item label="密码" prop="password"><el-input v-model="form.password" type="password" show-password size="large" placeholder="至少 8 个字符" autocomplete="new-password" /></el-form-item>
          <el-form-item label="确认密码" prop="password_confirm"><el-input v-model="form.password_confirm" type="password" show-password size="large" placeholder="再次输入密码" autocomplete="new-password" /></el-form-item>
          <button class="tech-button" type="button" :disabled="userStore.loading" @click="submit"><span>{{ userStore.loading ? '正在创建...' : '创建并进入平台' }}</span><b>→</b></button>
        </el-form>
        <p class="auth-switch">已有账号？<RouterLink to="/login">返回登录</RouterLink></p>
      </div>
    </section>
  </main>
</template>
