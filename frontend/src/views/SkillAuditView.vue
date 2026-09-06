<script setup>
import { onMounted, ref } from 'vue'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'
import { listPermissionAudits } from '../api/skills'

const audits = ref([])
const loading = ref(true)
const error = ref('')

function explain(err) {
  if (err.response?.status === 401) return '登录已过期，请重新登录。'
  if (err.response?.status === 403) return '当前账号没有查看权限审计的权限。'
  return err.response?.data?.detail || '权限审计加载失败，请重试。'
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    audits.value = await listPermissionAudits()
  } catch (err) {
    error.value = explain(err)
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <WorkspaceShell active="skill-audits">
    <div class="workspace-content model-page skills-page">
      <div class="page-title-row">
        <div><p class="workspace-eyebrow">SKILL GOVERNANCE</p><h1>Skill 权限审计</h1><p class="workspace-lead">查看第三方 Skill 的权限允许与拒绝记录。审计内容不包含请求中的敏感值。</p></div>
        <button class="text-action" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新审计' }}</button>
      </div>
      <section class="skills-panel">
        <div v-if="loading" class="state-panel" role="status">正在加载权限审计</div>
        <div v-else-if="error" class="state-panel state-panel--error" role="alert"><p>{{ error }}</p><button type="button" @click="load">重试</button></div>
        <div v-else-if="!audits.length" class="skills-empty">暂无权限审计记录</div>
        <table v-else class="skills-table"><thead><tr><th>时间</th><th>权限</th><th>结果</th><th>来源</th><th>上下文字段</th><th>调用者</th></tr></thead><tbody><tr v-for="audit in audits" :key="audit.id"><td>{{ new Date(audit.created_at).toLocaleString() }}</td><td>{{ audit.permission }}</td><td><span class="skills-chip" :class="{ off: !audit.allowed }">{{ audit.allowed ? '允许' : '拒绝' }}</span></td><td>{{ audit.installation_source }}</td><td>{{ (audit.context_keys || []).join(', ') || '无' }}</td><td>{{ audit.actor_username || '系统' }}</td></tr></tbody></table>
      </section>
    </div>
  </WorkspaceShell>
</template>

