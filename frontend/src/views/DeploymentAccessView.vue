<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { checkDeploymentAccess, getDeploymentAccess } from '../api/deploymentAccess'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'

const access = ref(null)
const loading = ref(true)
const checking = ref(false)
const error = ref('')

function explain(errorObject, fallback) {
  const data = errorObject.response?.data
  if (typeof data?.detail === 'string') return data.detail
  if (typeof data?.message === 'string') return data.message
  return fallback
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    access.value = await getDeploymentAccess()
  } catch (errorObject) {
    error.value = explain(errorObject, '访问入口配置暂时无法加载，请确认服务状态后重试。')
  } finally {
    loading.value = false
  }
}

async function check() {
  checking.value = true
  error.value = ''
  try {
    access.value = await checkDeploymentAccess()
  } catch (errorObject) {
    error.value = explain(errorObject, '访问入口检查失败，请检查反向代理和服务状态后重试。')
  } finally {
    checking.value = false
  }
}

async function copyAddress() {
  if (!access.value?.app_url) return
  try {
    await navigator.clipboard.writeText(access.value.app_url)
    ElMessage.success('用户访问地址已复制')
  } catch {
    error.value = '浏览器未允许自动复制，请手动选择地址复制。'
  }
}

onMounted(load)
</script>

<template>
  <WorkspaceShell active="access">
    <div class="workspace-content deployment-page">
      <div class="page-title-row">
        <div>
          <p class="workspace-eyebrow">PUBLIC ACCESS & DEPLOYMENT</p>
          <h1>用户访问入口</h1>
          <p class="workspace-lead">这里是管理员应该发给同事的唯一入口。系统不会展示后端、数据库、Redis、Docker 或 SSH 地址。</p>
        </div>
        <div class="page-actions"><button class="secondary-action" :disabled="loading || checking" @click="load">刷新配置</button><button class="primary-action" :disabled="loading || checking || !access?.configured" @click="check">{{ checking ? '检查中…' : '检查入口' }}</button></div>
      </div>

      <section v-if="loading" class="state-panel"><span class="loading-ring"></span><b>正在读取访问入口</b><p>请稍候，系统正在读取显式部署配置。</p></section>
      <section v-else-if="error" class="state-panel state-panel--error"><b>访问入口暂时不可用</b><p>{{ error }}</p><button @click="load">重新加载</button></section>
      <template v-else>
        <section v-if="!access.configured" class="state-panel state-panel--error"><b>尚未配置规范用户入口</b><p>{{ access.health_message }}</p><p class="deployment-access-hint">请在部署环境配置 <code>PUBLIC_APP_URL</code>，不能用后端 8000、数据库、Redis、Docker 或 SSH 地址替代。</p></section>
        <template v-else>
          <section class="deployment-access-card">
            <div class="deployment-access-card__heading"><div><small>SHARE THIS ADDRESS</small><h2>规范用户访问地址</h2></div><span class="status-chip" :class="access.health_status === 'healthy' ? 'is-online' : 'is-offline'"><i></i>{{ access.health_status_label }}</span></div>
            <div class="deployment-access-url"><code>{{ access.app_url }}</code><button class="secondary-action" @click="copyAddress">复制地址</button></div>
            <p class="deployment-access-warning">{{ access.warning }}</p>
          </section>
          <section class="deployment-access-grid">
            <article><small>访问范围</small><strong>{{ access.access_scope_label }}</strong><span>由显式配置判断，不枚举服务器网卡。</span></article>
            <article><small>协议与端口</small><strong>{{ access.protocol }} · {{ access.port }}</strong><span>{{ access.tls_status_label }}</span></article>
            <article><small>健康检查</small><strong>{{ access.health_status_label }}</strong><span>{{ access.health_message }}</span></article>
            <article><small>最近检查</small><strong>{{ access.last_checked_at || '尚未检查' }}</strong><span>检查不携带登录凭据。</span></article>
          </section>
        </template>
      </template>
    </div>
  </WorkspaceShell>
</template>
