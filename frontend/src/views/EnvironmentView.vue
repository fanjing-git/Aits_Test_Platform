<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'
import { useUserStore } from '../stores/user'
import { listProjects } from '../api/projects'
import * as api from '../api/environments'

const userStore = useUserStore()
const projects = ref([])
const projectId = ref('')
const environments = ref([])
const loading = ref(true)
const error = ref('')
const feedback = ref('')
const modal = ref(false)
const editing = ref(null)
const target = ref(null)
const busy = ref(false)
const checkingId = ref(null)
const checkError = ref('')
const formError = ref('')
const form = reactive({})
const secrets = reactive({})
let loadVersion = 0
const types = { dev: '开发环境', test: '测试环境', staging: '预发布环境', prod: '生产环境' }
const states = { unavailable: '不可用', maintenance: '维护中', available: '可用' }
const secretLabels = { database_config: '数据库连接配置', auth_config: '认证配置', variables: '环境变量' }
const selected = computed(() => projects.value.find(p => p.id === projectId.value))
const canManage = computed(() => !!selected.value && (userStore.user?.role === 'admin' || (userStore.user?.role === 'test_leader' && ['owner', 'manager'].includes(selected.value.current_role))))
const availableTypes = computed(() => Object.entries(types).filter(([key]) => key === editing.value?.name || !environments.value.some(e => e.name === key)))

function message(err, fallback) {
  if (err.response?.status === 403) return '你没有配置此项目环境的权限，请联系项目管理员。'
  if (err.response?.status === 401) return '登录已过期，请重新登录。'
  const data = err.response?.data
  if (typeof data?.detail === 'string') return data.detail
  const names = { ...secretLabels, name: '环境类型', base_url: '接口地址', health_check_url: '健康检查地址', project_id: '项目', status: '环境状态', non_field_errors: '配置' }
  if (data && typeof data === 'object') {
    const [key, value] = Object.entries(data)[0] || []
    if (key) return `${names[key] || '配置'}：${Array.isArray(value) ? value.join('；') : value}`
  }
  return fallback
}

async function loadEnvironments() {
  const version = ++loadVersion
  environments.value = []
  error.value = ''; feedback.value = ''; checkError.value = ''; loading.value = true
  try {
    const result = projectId.value ? await api.listEnvironments(projectId.value) : []
    if (version === loadVersion) environments.value = result
  } catch (err) {
    if (version === loadVersion) error.value = message(err, '环境加载失败，请检查服务后重试。')
  } finally { if (version === loadVersion) loading.value = false }
}

async function refresh(notify = false) {
  loading.value = true; error.value = ''; feedback.value = ''
  try {
    projects.value = await listProjects()
    if (!projects.value.some(p => p.id === projectId.value)) projectId.value = projects.value[0]?.id || ''
    await loadEnvironments()
    if (!error.value && notify) {
      feedback.value = `刷新完成 · ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`
      ElMessage.success('环境配置已刷新')
    }
  } catch (err) { error.value = message(err, '项目加载失败，请重试。'); loading.value = false }
}

function openForm(environment = null) {
  editing.value = environment
  Object.assign(form, { name: environment?.name || availableTypes.value[0]?.[0] || 'dev', base_url: environment?.base_url || '', description: environment?.description || '', status: environment?.status || 'unavailable', health_check_url: environment?.health_check_url || '' })
  for (const key of Object.keys(secretLabels)) secrets[key] = { mode: environment ? 'keep' : 'replace', text: '{}' }
  formError.value = ''; modal.value = true
}

function closeForm() {
  if (busy.value) return
  modal.value = false
  for (const key of Object.keys(secretLabels)) secrets[key] = { mode: 'keep', text: '{}' }
}

async function save() {
  formError.value = ''
  const payload = { ...form, project_id: projectId.value }
  for (const key of ['base_url', 'health_check_url']) {
    payload[key] = payload[key].trim()
    if (key === 'health_check_url' && !payload[key]) continue
    try {
      const url = new URL(payload[key])
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error()
    } catch { formError.value = '请填写有效的 HTTP/HTTPS 地址，认证信息请放入认证配置。'; return }
  }
  for (const key of Object.keys(secretLabels)) {
    if (secrets[key].mode === 'keep') continue
    if (secrets[key].mode === 'clear') { payload[key] = {}; continue }
    try {
      const value = JSON.parse(secrets[key].text)
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error()
      payload[key] = value
    } catch { formError.value = `${secretLabels[key]}必须是 JSON 对象，例如 {}。`; return }
  }
  busy.value = true
  try {
    if (editing.value) await api.updateEnvironment(editing.value.id, payload)
    else await api.createEnvironment(payload)
    ElMessage.success(editing.value ? '环境配置已更新' : '环境已创建')
    busy.value = false; closeForm()
    await loadEnvironments()
  } catch (err) { formError.value = message(err, '保存失败，请检查配置后重试。') }
  finally { busy.value = false }
}

async function checkHealth(environment) {
  if (checkingId.value) return
  checkingId.value = environment.id; checkError.value = ''
  const requestedProject = projectId.value
  try {
    const result = await api.checkEnvironment(environment.id)
    if (projectId.value !== requestedProject) return
    environments.value = environments.value.map(item => item.id === result.id ? result : item)
    if (result.health_status === 'healthy') ElMessage.success(result.health_message)
    else ElMessage.warning(result.health_message)
  } catch (err) {
    if (projectId.value === requestedProject) {
      checkError.value = message(err, '健康检查未完成，请重试。')
      ElMessage.error(checkError.value)
    }
  } finally { checkingId.value = null }
}

async function remove() {
  busy.value = true; formError.value = ''
  try {
    await api.deleteEnvironment(target.value.id)
    target.value = null
    ElMessage.success('环境及其配置已删除')
    await loadEnvironments()
  } catch (err) { formError.value = message(err, '删除失败，请重试。') }
  finally { busy.value = false }
}

onMounted(() => refresh())
</script>

<template>
  <WorkspaceShell active="environments">
    <div class="workspace-content model-page environment-page">
      <div class="page-title-row"><div><p class="workspace-eyebrow">TEST ENVIRONMENTS</p><h1>环境管理</h1><p class="workspace-lead">按项目管理测试地址、认证与环境配置。</p></div><button v-if="canManage" class="primary-action environment-create" :disabled="loading || !availableTypes.length" @click="openForm()">＋ 创建环境</button></div>
      <section class="environment-toolbar"><label>当前项目<select v-model="projectId" :disabled="loading || !projects.length" @change="loadEnvironments"><option v-if="!projects.length" value="">暂无可访问项目</option><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select></label><button class="text-action" :disabled="loading" :aria-busy="loading" @click="refresh(true)">{{ loading ? '正在刷新…' : '刷新环境' }}</button></section>
      <p v-if="feedback" class="environment-notice" role="status">{{ feedback }}</p>
      <p v-if="selected && !canManage" class="environment-notice">当前为只读模式。配置环境需要平台管理员，或具备项目管理权限的测试负责人。</p>
      <p v-if="checkError" class="form-error" role="alert">{{ checkError }}</p>
      <section class="model-panel">
        <div v-if="loading" class="state-panel" role="status"><span class="loading-ring"></span><b>正在加载环境</b></div>
        <div v-else-if="error" class="state-panel state-panel--error" role="alert"><b>暂时无法加载</b><p>{{ error }}</p><button @click="refresh()">重新加载</button></div>
        <div v-else-if="!selected" class="state-panel"><b>还没有可访问的项目</b><p>先创建项目，或请项目管理员将你加入项目。</p><RouterLink to="/workspace/projects">前往项目与智能体</RouterLink></div>
        <div v-else-if="!environments.length" class="state-panel"><b>此项目尚未配置环境</b><p>{{ canManage ? '创建开发、测试、预发布或生产环境，每种类型最多一个。' : '请联系项目管理员配置环境。' }}</p></div>
        <div v-else class="environment-grid">
          <article v-for="environment in environments" :key="environment.id" class="environment-card">
            <header><h2>{{ environment.name_label }}</h2><span class="type-chip">{{ environment.name }}</span></header>
            <p class="environment-url">{{ environment.base_url }}</p><p>{{ environment.description || '暂无说明' }}</p>
            <dl><div><dt>环境状态</dt><dd>{{ environment.status_label }}</dd></div><div><dt>健康状态</dt><dd>{{ environment.health_status_label }}</dd></div><div v-for="(label, key) in secretLabels" :key="key"><dt>{{ label }}</dt><dd>{{ environment['has_' + key] ? '已安全配置' : '未配置' }}</dd></div></dl>
            <p v-if="['staging', 'prod'].includes(environment.name)" class="environment-notice">{{ environment.name === 'prod' ? '生产环境：测试执行需管理员审批。' : '预发布环境：测试执行需负责人审批。' }}</p>
            <p v-if="environment.health_checked_at" class="environment-notice">最近检查：{{ new Date(environment.health_checked_at).toLocaleString('zh-CN') }} · {{ environment.health_latency_ms }} ms<br>{{ environment.health_message }}</p>
            <div v-if="environment.can_manage" class="row-actions"><button class="environment-check" :disabled="!!checkingId" @click="checkHealth(environment)">{{ checkingId === environment.id ? '正在检查…' : '健康检查' }}</button><button class="environment-edit" @click="openForm(environment)">编辑</button><button class="danger environment-delete" @click="target = environment; formError = ''">删除</button></div>
          </article>
        </div>
      </section>
      <p class="environment-notice">健康检查会访问配置的检查地址并更新状态；维护中的环境不会自动恢复为可用。每5分钟自动检查尚未启用。</p>
    </div>
    <Teleport to="body">
      <div v-if="modal" class="modal-backdrop" @click.self="closeForm">
        <section class="config-modal environment-modal" role="dialog" aria-modal="true" aria-labelledby="environment-title">
          <header><div><small>{{ selected?.name }}</small><h2 id="environment-title">{{ editing ? '编辑环境' : '创建环境' }}</h2></div><button aria-label="关闭" :disabled="busy" @click="closeForm">×</button></header>
          <form @submit.prevent="save">
            <fieldset class="config-form" :disabled="busy">
              <label>环境类型<select v-model="form.name" :disabled="!!editing" name="name"><option v-for="[value, label] in availableTypes" :key="value" :value="value">{{ label }}</option></select></label>
              <label>接口基础地址 *<input v-model="form.base_url" name="base_url" required placeholder="https://test.example.com"></label>
              <label>环境说明<textarea v-model="form.description" name="description" rows="2"></textarea></label>
              <label>环境状态<select v-model="form.status" name="status"><option v-for="(label, value) in states" :key="value" :value="value">{{ label }}</option></select></label>
              <label>健康检查地址<input v-model="form.health_check_url" name="health_check_url" placeholder="例如：http://127.0.0.1:8000/api/health/"></label>
              <section v-for="(label, key) in secretLabels" :key="key" class="environment-secret"><label>{{ label }}<select v-model="secrets[key].mode" :name="key + '_mode'"><option v-if="editing" value="keep">保留现有配置</option><option value="replace">{{ editing ? '替换配置' : '设置配置' }}</option><option v-if="editing" value="clear">清空配置</option></select></label><label v-if="secrets[key].mode === 'replace'">{{ label }}内容（JSON）<textarea v-model="secrets[key].text" :name="key" rows="3" spellcheck="false" autocomplete="off"></textarea></label><p v-if="secrets[key].mode === 'clear'" class="form-error">保存后会清空{{ label }}，依赖此配置的测试可能失败。</p><small>加密保存，不读取或回显现有内容。替换时请填写完整配置。</small></section>
              <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
            </fieldset>
            <footer><button type="button" class="secondary-action" :disabled="busy" @click="closeForm">取消</button><button type="submit" class="primary-action" :disabled="busy">{{ busy ? '正在保存…' : '保存环境' }}</button></footer>
          </form>
        </section>
      </div>
      <div v-if="target" class="modal-backdrop" @click.self="!busy && (target = null)"><section class="confirm-modal" role="alertdialog" aria-modal="true"><h2>删除{{ target.name_label }}？</h2><p>将删除项目“{{ selected?.name }}”中此环境的地址和全部配置，无法撤销。</p><p v-if="formError" class="form-error" role="alert">{{ formError }}</p><div><button class="secondary-action" :disabled="busy" @click="target = null">取消</button><button class="danger-action" :disabled="busy" @click="remove">{{ busy ? '正在删除…' : '确认删除' }}</button></div></section></div>
    </Teleport>
  </WorkspaceShell>
</template>
