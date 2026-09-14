<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'
import * as api from '../api/skills'

const installations = ref([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const formError = ref('')
const selectedFile = ref(null)
const selectedFolderFiles = ref([])
const fileInput = ref(null)
const folderInput = ref(null)
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
const statusText = { pending: '待校验', verified: '已校验', installed: '已安装', failed: '失败', rolled_back: '已回滚', uninstalled: '已卸载' }
const sourceText = { local: '本地文件', github: 'GitHub', skillhub: 'SkillHub', package: '下载包' }
const permissionLabels = { network: '网络', file: '文件', database: '数据库', external_command: '外部命令', model: '模型', knowledge: '知识库', environment_credentials: '环境凭据' }
const sourceDefaults = { github: 'https://github.com/example/skill?ref=v1.0.0', skillhub: 'https://skillhub.example/skills/example?version=1.0.0', package: 'https://downloads.example/skill-1.0.0.zip' }
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
async function digestFile(file) {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(digest)).map(byte => byte.toString(16).padStart(2, '0')).join('')
}
function chooseFile(event) {
  const file = event.target.files?.[0] || null
  selectedFile.value = file
  selectedFolderFiles.value = []
  formError.value = ''
  if (file) form.source_url = `local://${file.name}`
}
function chooseFolder(event) {
  const files = Array.from(event.target.files || [])
  selectedFile.value = null
  selectedFolderFiles.value = files
  formError.value = ''
  const firstPath = files[0]?.webkitRelativePath || files[0]?.name || ''
  const folderName = firstPath.split('/')[0]
  if (folderName) form.source_url = `local://${folderName}`
}
function changeSource() {
  if (form.source_type !== 'local') {
    selectedFile.value = null
    selectedFolderFiles.value = []
    if (fileInput.value) fileInput.value.value = ''
    if (folderInput.value) folderInput.value.value = ''
    if (form.source_url.startsWith('local://')) form.source_url = sourceDefaults[form.source_type]
  }
}
function bytesBase64(bytes) {
  let binary = ''
  const chunkSize = 0x8000
  for (let index = 0; index < bytes.length; index += chunkSize) binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize))
  return btoa(binary)
}
async function fileBytesBase64(file) {
  return bytesBase64(new Uint8Array(await file.arrayBuffer()))
}
async function buildFolderArtifact(files) {
  if (!files.length || files.length > 500) throw new Error('Skills 文件夹不能为空且不能超过 500 个文件。')
  const encoder = new TextEncoder()
  const entries = []
  const chunks = []
  let totalSize = 0
  for (const file of files) {
    const path = String(file.webkitRelativePath || file.name || '').replaceAll('\\', '/')
    if (!path || path.split('/').some((part) => !part || part === '.' || part === '..')) throw new Error('Skills 文件夹包含不安全的文件路径。')
    const content = new Uint8Array(await file.arrayBuffer())
    totalSize += content.length
    if (totalSize > 50 * 1024 * 1024) throw new Error('Skills 文件夹不能超过 50 MB。')
    entries.push({ path, content })
  }
  const paths = new Set()
  for (const entry of entries) {
    const key = entry.path.toLowerCase()
    if (paths.has(key)) throw new Error('Skills 文件夹包含重复文件路径。')
    paths.add(key)
  }
  if (!entries.some((entry) => entry.path.split('/').pop().toLowerCase() === 'skill.md')) throw new Error('Skills 文件夹必须包含 SKILL.md。')
  entries.sort((left, right) => left.path.localeCompare(right.path))
  for (const entry of entries) chunks.push(encoder.encode(entry.path), new Uint8Array([0]), encoder.encode(String(entry.content.length)), new Uint8Array([0]), entry.content)
  const canonical = new Uint8Array(chunks.reduce((total, chunk) => total + chunk.length, 0))
  let offset = 0
  for (const chunk of chunks) { canonical.set(chunk, offset); offset += chunk.length }
  return { canonical, artifactFiles: entries.map((entry) => ({ path: entry.path, content_base64: bytesBase64(entry.content) })) }
}
async function digestBytes(bytes) {
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest)).map(byte => byte.toString(16).padStart(2, '0')).join('')
}
async function create() {
  formError.value = ''; const manifest = parseManifest(); if (!manifest) return
  if (!form.source_url.trim()) { formError.value = '请输入来源地址。'; return }
  if (form.source_type === 'local' && !selectedFile.value && !selectedFolderFiles.value.length) { formError.value = '请选择 Skill 压缩包或包含 SKILL.md 的文件夹。'; return }
  let folderArtifact = null
  if (selectedFolderFiles.value.length) {
    try { folderArtifact = await buildFolderArtifact(selectedFolderFiles.value); manifest.file_hash = await digestBytes(folderArtifact.canonical); form.manifest = JSON.stringify(manifest, null, 2) } catch (err) { formError.value = err.message || '无法读取 Skills 文件夹，请重新选择。'; return }
  }
  if (selectedFile.value) {
    if (selectedFile.value.size > 50 * 1024 * 1024) { formError.value = 'Skill 文件不能超过 50 MB。'; return }
    saving.value = true
    try { manifest.file_hash = await digestFile(selectedFile.value); form.manifest = JSON.stringify(manifest, null, 2) } catch { formError.value = '无法读取 Skill 文件，请重新选择。'; saving.value = false; return }
  }
  try {
    const created = await api.createInstallation({ source_type: form.source_type, source_url: form.source_url.trim(), manifest })
    if (folderArtifact) await api.verifyInstallation(created.id, { artifact_files: folderArtifact.artifactFiles, artifact_version: manifest.version })
    else if (selectedFile.value) await api.verifyInstallation(created.id, { artifact_base64: await fileBytesBase64(selectedFile.value), artifact_version: manifest.version })
    selectedFile.value = null
    selectedFolderFiles.value = []
    if (fileInput.value) fileInput.value.value = ''
    if (folderInput.value) folderInput.value.value = ''
    await load()
  } catch (err) { formError.value = explain(err, '来源校验失败，请检查地址、文件和 Manifest。') } finally { saving.value = false }
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
      <div class="page-title-row"><div><p class="workspace-eyebrow">SKILL GOVERNANCE</p><h1>第三方 Skill 安装</h1><p class="workspace-lead">添加来源并锁定版本，完成清单校验、审批、安装、回滚和卸载。业务页面会自动编排已启用 Skill，此处不要求用户手工填写权限。</p></div><button class="text-action" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新' }}</button></div>
      <section class="skills-panel" style="margin-bottom:16px"><h2>添加来源</h2><form class="skills-form" @submit.prevent="create"><label>来源类型<select v-model="form.source_type" @change="changeSource"><option value="local">导入本地文件或文件夹</option><option value="github">GitHub</option><option value="skillhub">SkillHub</option><option value="package">下载包</option></select></label><label v-if="form.source_type==='local'">Skill 压缩包<input ref="fileInput" type="file" accept=".zip,.whl,.tar.gz,.tgz,.json" @change="chooseFile"><small v-if="selectedFile" class="skills-hint">{{ selectedFile.name }} · {{ Math.ceil(selectedFile.size / 1024) }} KB</small></label><label v-if="form.source_type==='local'">Skills 文件夹<input ref="folderInput" type="file" webkitdirectory directory multiple @change="chooseFolder"><small class="skills-hint">选择解压后的文件夹；系统要求其中包含 SKILL.md，最多 500 个文件、总大小 50 MB。</small><small v-if="selectedFolderFiles.length" class="skills-hint">已选择文件夹：{{ (selectedFolderFiles[0].webkitRelativePath || selectedFolderFiles[0].name).split('/')[0] }} · {{ selectedFolderFiles.length }} 个文件</small></label><label>来源地址 / 路径<input v-model="form.source_url" required></label><label>Manifest JSON<textarea v-model="form.manifest" rows="8" required></textarea></label><p class="skills-hint">本地文件或文件夹只在浏览器中计算 SHA-256 并提交受控校验，不下载、不执行第三方代码。Manifest 仍需包含 name、version、author、license 和完整 permissions。</p><p v-if="formError" class="skills-error" role="alert">{{ formError }}</p><button class="primary-action" type="submit" :disabled="saving">{{ saving ? '导入中…' : '导入 Skill / 提交安装请求' }}</button></form></section>
      <section class="skills-panel"><div v-if="loading" class="state-panel" role="status">正在加载安装记录</div><div v-else-if="error" class="state-panel state-panel--error" role="alert"><p>{{ error }}</p><button type="button" @click="load">重试</button></div><div v-else-if="!installations.length" class="skills-empty">暂无安装请求</div><table v-else class="skills-table"><thead><tr><th>来源</th><th>版本</th><th>权限</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="item in installations" :key="item.id"><td><b>{{ sourceText[item.source_type] || item.source_type }}</b><br><small>{{ item.source_url }}</small></td><td>v{{ item.version }}</td><td><span v-for="name in permissionNames" :key="name" v-show="item.permissions?.[name]" class="skills-chip">{{ permissionLabels[name] || name }}</span><span v-if="!permissionNames.some(name => item.permissions?.[name])" class="skills-hint">无</span></td><td><span class="skills-chip" :class="{ off: ['failed','rolled_back','uninstalled'].includes(item.status) }">{{ item.status_label || statusText[item.status] || item.status }}</span><p v-if="item.error_message" class="skills-error">{{ item.error_message }}</p></td><td><div class="skills-actions"><button v-if="item.status==='pending' || item.status==='failed'" class="text-action" :disabled="busyIds.has(item.id)" @click="verify(item)">校验</button><button v-if="item.status==='verified'" class="text-action" :disabled="busyIds.has(item.id)" @click="transition(item,'approveInstallation','审批')">审批</button><button v-if="item.status==='verified' && item.approved_by" class="text-action" :disabled="busyIds.has(item.id)" @click="transition(item,'installSkillInstallation','安装')">安装</button><button v-if="item.status==='installed'" class="text-action" :disabled="busyIds.has(item.id)" @click="transition(item,'rollbackInstallation','回滚')">回滚</button><button v-if="item.status==='installed'" class="danger text-action" :disabled="busyIds.has(item.id)" @click="transition(item,'uninstallInstallation','卸载')">卸载</button></div></td></tr></tbody></table></section>
    </div>
  </WorkspaceShell>
</template>
