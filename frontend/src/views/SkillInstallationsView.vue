<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'
import * as api from '../api/skills'

const installations = ref([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const formError = ref('')
const form = reactive({
  source_type: 'github',
  source_url: 'https://github.com/example/skill?ref=v1.0.0',
  manifest: JSON.stringify({
    name: 'example-skill', version: '1.0.0', author: 'Example', license: 'MIT',
    permissions: { network: false, file: false, database: false, external_command: false, model: false, knowledge: false, environment_credentials: false },
    file_hash: '',
  }, null, 2),
})

const busyIds = ref(new Set())
const statusText = { pending: 'Pending', verified: 'Verified', installed: 'Installed', failed: 'Failed', rolled_back: 'Rolled back', uninstalled: 'Uninstalled' }
const permissionNames = computed(() => ['network', 'file', 'database', 'external_command', 'model', 'knowledge', 'environment_credentials'])

function asList(value) { return Array.isArray(value) ? value : (value?.results || []) }
function explain(err, fallback) {
  if (err.response?.status === 401) return '登录已过期，请重新登录。'
  if (err.response?.status === 403) return '当前账号没有管理第三方 Skill 的权限。'
  return err.response?.data?.detail || fallback
}
async function load() {
  loading.value = true; error.value = ''
  try { installations.value = asList(await api.listInstallations()) } catch (err) { error.value = explain(err, '安装记录加载失败，请重试。') } finally { loading.value = false }
}
function parseManifest() {
  try { return JSON.parse(form.manifest) } catch { formError.value = 'Manifest 必须是有效 JSON。'; return null }
}
async function create() {
  formError.value = ''; const manifest = parseManifest(); if (!manifest) return
  if (!form.source_url.trim()) { formError.value = '请输入来源地址。'; return }
  saving.value = true
  try { await api.createInstallation({ source_type: form.source_type, source_url: form.source_url.trim(), manifest }); form.manifest = JSON.stringify(manifest, null, 2); await load() } catch (err) { formError.value = explain(err, '来源校验失败，请检查地址和 Manifest。') } finally { saving.value = false }
}
function setBusy(id, value) { const next = new Set(busyIds.value); value ? next.add(id) : next.delete(id); busyIds.value = next }
function encode(value) { return btoa(unescape(encodeURIComponent(value))) }
async function verify(item) {
  const raw = window.prompt('请输入用于受控校验的文本（系统只计算哈希，不下载或执行代码）：', 'skill-artifact-fixture')
  if (raw === null) return
  setBusy(item.id, true)
  try { await api.verifyInstallation(item.id, { artifact_base64: encode(raw), artifact_version: item.version }); await load() } catch (err) { error.value = explain(err, '校验失败，请检查文件内容和版本。') } finally { setBusy(item.id, false) }
}
async function transition(item, action, label) {
  if (!window.confirm(`确认${label} ${item.source_url}？`)) return
  setBusy(item.id, true); error.value = ''
  try { await api[action](item.id); await load() } catch (err) { error.value = explain(err, `${label}失败，请重试。`) } finally { setBusy(item.id, false) }
}
onMounted(load)
</script>

<template>
  <WorkspaceShell active="skill-installations">
    <div class="workspace-content model-page skills-page">
      <div class="page-title-row"><div><p class="workspace-eyebrow">SKILL GOVERNANCE</p><h1>Third-party Skill installations</h1><p class="workspace-lead">添加来源并锁定版本，完成清单校验、审批、安装、回滚和卸载。所有校验在受控边界内执行。</p></div><button class="text-action" :disabled="loading" @click="load">{{ loading ? 'Loading...' : 'Refresh' }}</button></div>
      <section class="skills-panel" style="margin-bottom:16px"><h2>添加来源</h2><form class="skills-form" @submit.prevent="create"><label>Source type<select v-model="form.source_type"><option value="local">Local</option><option value="github">GitHub</option><option value="skillhub">SkillHub</option><option value="package">Package</option></select></label><label>Source URL / path<input v-model="form.source_url" required></label><label>Manifest JSON<textarea v-model="form.manifest" rows="8" required></textarea></label><p class="skills-hint">Manifest 需包含 name、version、author、license 和完整 permissions。远程来源只做地址和清单校验。</p><p v-if="formError" class="skills-error" role="alert">{{ formError }}</p><button class="primary-action" type="submit" :disabled="saving">{{ saving ? 'Submitting...' : 'Submit installation request' }}</button></form></section>
      <section class="skills-panel"><div v-if="loading" class="state-panel" role="status">正在加载安装记录</div><div v-else-if="error" class="state-panel state-panel--error" role="alert"><p>{{ error }}</p><button type="button" @click="load">Retry</button></div><div v-else-if="!installations.length" class="skills-empty">暂无安装请求</div><table v-else class="skills-table"><thead><tr><th>Source</th><th>Version</th><th>Permissions</th><th>Status</th><th>Actions</th></tr></thead><tbody><tr v-for="item in installations" :key="item.id"><td><b>{{ item.source_type }}</b><br><small>{{ item.source_url }}</small></td><td>v{{ item.version }}</td><td><span v-for="name in permissionNames" :key="name" v-show="item.permissions?.[name]" class="skills-chip">{{ name }}</span><span v-if="!permissionNames.some(name => item.permissions?.[name])" class="skills-hint">none</span></td><td><span class="skills-chip" :class="{ off: ['failed','rolled_back','uninstalled'].includes(item.status) }">{{ item.status_label || statusText[item.status] || item.status }}</span><p v-if="item.error_message" class="skills-error">{{ item.error_message }}</p></td><td><div class="skills-actions"><button v-if="item.status==='pending' || item.status==='failed'" class="text-action" :disabled="busyIds.has(item.id)" @click="verify(item)">Verify</button><button v-if="item.status==='verified'" class="text-action" :disabled="busyIds.has(item.id)" @click="transition(item,'approveInstallation','approve')">Approve</button><button v-if="item.status==='verified' && item.approved_by" class="text-action" :disabled="busyIds.has(item.id)" @click="transition(item,'installSkillInstallation','install')">Install</button><button v-if="item.status==='installed'" class="text-action" :disabled="busyIds.has(item.id)" @click="transition(item,'rollbackInstallation','rollback')">Rollback</button><button v-if="item.status==='installed'" class="danger text-action" :disabled="busyIds.has(item.id)" @click="transition(item,'uninstallInstallation','uninstall')">Uninstall</button></div></td></tr></tbody></table></section>
    </div>
  </WorkspaceShell>
</template>
