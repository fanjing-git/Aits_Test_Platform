<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'
import { useUserStore } from '../stores/user'
import { listProjects } from '../api/projects'
import { listEnvironments } from '../api/environments'
import * as api from '../api/tests'

const projects = ref([])
const userStore = useUserStore()
const environments = ref([])
const cases = ref([])
const runs = ref([])
const projectId = ref('')
const loading = ref(true)
const error = ref('')
const notice = ref('')
const formError = ref('')
const busy = ref(false)
const selectedCaseIds = ref([])
const caseForm = reactive({ case_id: '', title: '', method: 'GET', path: '/api/health/', expected_result: '返回 2xx', steps: '' })
const runForm = reactive({ name: '', mode: 'immediate', environment_id: '', script_path: '' })

const selectedProject = computed(() => projects.value.find(item => item.id === projectId.value))
const currentRole = computed(() => selectedProject.value?.current_role || '')
const canWriteCase = computed(() => userCanOperate(['admin', 'test_leader', 'tester']) && ['owner', 'manager', 'member'].includes(currentRole.value))
const canExecute = computed(() => userCanOperate(['admin', 'test_leader', 'tester', 'developer']) && ['owner', 'manager', 'member'].includes(currentRole.value))
const selectedCases = computed(() => cases.value.filter(item => selectedCaseIds.value.includes(item.id)))
const availableCases = computed(() => cases.value.filter(item => item.steps?.length))

function userCanOperate(roles) {
  return roles.includes(userStore.user?.role)
}

function explain(err, fallback) {
  if (err.response?.status === 401) return '登录已过期，请重新登录。'
  if (err.response?.status === 403) return '当前账号没有执行此操作的权限。'
  if (err.response?.status >= 500) return '测试服务暂时不可用，请稍后重试。'
  if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') return '请求超时，请检查服务状态后重试。'
  const data = err.response?.data
  if (typeof data?.detail === 'string') return data.detail
  const first = data && Object.values(data)[0]
  return Array.isArray(first) ? first.join('；') : (first || fallback)
}

async function loadProjectAssets() {
  if (!projectId.value) { environments.value = []; cases.value = []; runs.value = []; return }
  const [envs, testCases, testRuns] = await Promise.all([
    listEnvironments(projectId.value), api.listTestCases(projectId.value), api.listTestRuns(projectId.value),
  ])
  environments.value = envs
  cases.value = testCases
  runs.value = testRuns
  if (!environments.value.some(item => item.id === runForm.environment_id)) runForm.environment_id = environments.value[0]?.id || ''
  selectedCaseIds.value = selectedCaseIds.value.filter(id => cases.value.some(item => item.id === id))
}

async function load() {
  loading.value = true; error.value = ''; notice.value = ''
  try {
    projects.value = await listProjects()
    if (!projects.value.some(item => item.id === projectId.value)) projectId.value = projects.value[0]?.id || ''
    await loadProjectAssets()
  } catch (err) { error.value = explain(err, '测试执行数据加载失败，请重试。') } finally { loading.value = false }
}

async function changeProject() {
  selectedCaseIds.value = []; runForm.environment_id = ''; await loadProjectAssets()
}

function toggleCase(id) {
  selectedCaseIds.value = selectedCaseIds.value.includes(id)
    ? selectedCaseIds.value.filter(item => item !== id)
    : [...selectedCaseIds.value, id]
}

function resetCaseForm() {
  Object.assign(caseForm, { case_id: `API-${String(cases.value.length + 1).padStart(3, '0')}`, title: '', method: 'GET', path: '/api/health/', expected_result: '返回 2xx', steps: '' })
  formError.value = ''
}

async function saveCase() {
  formError.value = ''
  if (!caseForm.case_id.trim() || !caseForm.title.trim() || !caseForm.path.trim()) { formError.value = '用例编号、标题和接口路径不能为空。'; return }
  const steps = [{ method: caseForm.method, path: caseForm.path.trim(), expected_status: 200 }]
  if (caseForm.steps.trim()) {
    try { const extra = JSON.parse(caseForm.steps); if (!Array.isArray(extra)) throw new Error(); steps.splice(0, steps.length, ...extra) } catch { formError.value = '扩展步骤必须是 JSON 数组。'; return }
  }
  busy.value = true
  try {
    await api.createTestCase({ project_id: projectId.value, case_id: caseForm.case_id.trim(), title: caseForm.title.trim(), steps, expected_result: caseForm.expected_result.trim() || '按接口断言判断' })
    notice.value = '测试用例已创建，可以在右侧选择后执行。'; ElMessage.success('测试用例已创建'); resetCaseForm(); await loadProjectAssets()
  } catch (err) { formError.value = explain(err, '测试用例创建失败，请检查字段后重试。') } finally { busy.value = false }
}

async function createRun() {
  formError.value = ''
  if (!runForm.name.trim()) { formError.value = '请输入执行名称。'; return }
  if (!selectedCaseIds.value.length) { formError.value = '请至少选择一个可执行用例。'; return }
  if (runForm.mode === 'immediate' && selectedCaseIds.value.length !== 1) { formError.value = '立即执行模式只能选择一个用例。'; return }
  if (runForm.mode === 'script' && !runForm.script_path.trim()) { formError.value = '脚本执行模式必须填写工作目录中的脚本路径。'; return }
  busy.value = true
  try {
    await api.createTestRun({ project_id: projectId.value, environment_id: runForm.environment_id || null, name: runForm.name.trim(), mode: runForm.mode, test_case_ids: selectedCaseIds.value, execution_config: runForm.mode === 'script' ? { script_path: runForm.script_path.trim() } : {} })
    notice.value = '执行任务已创建，点击“执行”开始真实本地 API 联调。'; ElMessage.success('执行任务已创建'); runForm.name = ''; await loadProjectAssets()
  } catch (err) { formError.value = explain(err, '执行任务创建失败，请检查环境和用例选择。') } finally { busy.value = false }
}

async function execute(run) {
  if (busy.value) return
  busy.value = true; formError.value = ''; notice.value = ''
  try { await api.executeTestRun(run.id); notice.value = `执行“${run.name}”已完成，结果已保存。`; ElMessage.success('测试执行完成'); await loadProjectAssets() } catch (err) { formError.value = explain(err, '测试执行失败，请稍后重试。') } finally { busy.value = false }
}

onMounted(() => { resetCaseForm(); load() })
</script>

<template>
  <WorkspaceShell active="tests">
    <div class="workspace-content test-execution-page">
      <div class="page-title-row"><div><p class="workspace-eyebrow">TEST EXECUTION</p><h1>测试执行</h1><p class="workspace-lead">选择项目与接口用例，在受控环境中立即执行、脚本执行或全量执行。</p></div><button class="secondary-action" :disabled="loading || busy" @click="load">{{ loading ? '正在加载…' : '刷新数据' }}</button></div>
      <section class="test-execution-toolbar"><label>当前项目<select v-model="projectId" :disabled="loading || !projects.length" @change="changeProject"><option v-if="!projects.length" value="">暂无可访问项目</option><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select></label><span v-if="selectedProject">当前角色：{{ currentRole || '只读' }}</span></section>
      <p v-if="notice" class="test-execution-notice" role="status">{{ notice }}</p>
      <p v-if="error" class="test-execution-error" role="alert">{{ error }} <button class="text-action" @click="load">重新加载</button></p>
      <section v-if="loading" class="state-panel" role="status"><span class="loading-ring"></span><b>正在加载测试执行工作台</b></section>
      <section v-else-if="!selectedProject" class="state-panel"><b>还没有可访问的项目</b><p>请先创建项目，或联系项目管理员加入项目。</p><RouterLink to="/workspace/projects">前往项目与智能体</RouterLink></section>
      <template v-else>
        <p v-if="!canExecute" class="test-execution-notice">当前为只读模式。测试执行需要项目成员身份和平台执行权限。</p>
        <p v-if="formError" class="test-execution-error" role="alert">{{ formError }}</p>
        <div class="test-execution-grid">
          <section class="test-execution-panel"><header><div><p class="panel-kicker">CASE LIBRARY</p><h2>接口测试用例</h2></div><span>{{ cases.length }} 条</span></header><p v-if="!cases.length" class="test-execution-empty">暂无测试用例，请先在下方创建第一条接口用例。</p><div v-else class="test-case-list"><label v-for="item in cases" :key="item.id" class="test-case-item" :class="{ selected: selectedCaseIds.includes(item.id) }"><input type="checkbox" :checked="selectedCaseIds.includes(item.id)" :disabled="!canExecute || !item.steps?.length" @change="toggleCase(item.id)"><span><b>{{ item.case_id }} · {{ item.title }}</b><small>{{ item.steps?.[0]?.method || '—' }} {{ item.steps?.[0]?.path || '不可执行' }} · {{ item.priority_label }}</small></span></label></div><form v-if="canWriteCase" class="test-execution-form" @submit.prevent="saveCase"><h3>创建接口用例</h3><label>用例编号<input v-model="caseForm.case_id" required></label><label>用例标题<input v-model="caseForm.title" required></label><div class="test-execution-form-row"><label>方法<select v-model="caseForm.method"><option>GET</option><option>POST</option><option>PUT</option><option>PATCH</option><option>DELETE</option></select></label><label>路径<input v-model="caseForm.path" required placeholder="/api/health/"></label></div><label>预期结果<input v-model="caseForm.expected_result"></label><label>扩展步骤（可选 JSON）<textarea v-model="caseForm.steps" rows="3" placeholder='[{"method":"GET","path":"/api/health/","expected_status":200}]'></textarea></label><button class="primary-action" :disabled="busy">{{ busy ? '保存中…' : '保存用例' }}</button></form></section>
          <section class="test-execution-panel"><header><div><p class="panel-kicker">EXECUTION CONTROL</p><h2>执行任务</h2></div><span>{{ selectedCaseIds.length }} 条已选</span></header><form v-if="canExecute" class="test-execution-form test-execution-form--top" @submit.prevent="createRun"><label>执行名称<input v-model="runForm.name" required placeholder="例如：测试环境健康检查"></label><div class="test-execution-form-row"><label>执行模式<select v-model="runForm.mode"><option value="immediate">立即执行（单用例）</option><option value="script">脚本执行</option><option value="full">全量执行（多用例）</option></select></label><label>执行环境<select v-model="runForm.environment_id"><option value="">未选择（执行时会安全失败）</option><option v-for="environment in environments" :key="environment.id" :value="environment.id">{{ environment.name_label }} · {{ environment.status_label }}</option></select></label></div><label v-if="runForm.mode === 'script'">脚本路径<input v-model="runForm.script_path" placeholder="例如：scripts/health_check.py"><small>脚本必须位于该执行工作目录，并输出约定 JSON。</small></label><button class="primary-action" :disabled="busy || !selectedCaseIds.length">创建执行任务</button></form><p v-else class="test-execution-empty">你可以查看执行记录；创建和执行任务需要操作权限。</p><div class="run-list"><p v-if="!runs.length" class="test-execution-empty">暂无执行记录。</p><article v-for="run in runs" :key="run.id" class="run-item"><div><b>{{ run.name }}</b><small>{{ run.mode_label }} · {{ run.status_label }} · {{ run.test_cases?.length || 0 }} 条用例</small><small v-if="run.summary?.error_message" class="run-error">{{ run.summary.error_message }}</small></div><div class="run-item-actions"><span class="run-status" :class="`run-status--${run.status}`">{{ run.status_label }}</span><button v-if="canExecute" class="text-action" :disabled="busy || run.status === 'running'" @click="execute(run)">{{ run.status === 'pending' ? '执行' : '重新执行' }}</button></div><div v-if="run.results?.length" class="run-results"><span v-for="result in run.results" :key="result.id" :class="`result-${result.status}`">{{ result.case_id }}：{{ result.status_label }}<small v-if="result.status_code"> · {{ result.status_code }}</small></span></div></article></div></section>
        </div>
      </template>
    </div>
  </WorkspaceShell>
</template>

<style scoped>
.test-execution-toolbar, .test-execution-panel header, .run-item, .run-item-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.test-execution-toolbar { margin: 0 0 20px; padding: 16px 20px; border: 1px solid rgb(104 221 211 / 14%); background: rgb(8 25 38 / 72%); color: #8da8aa; font-size: 12px; }
.test-execution-toolbar label, .test-execution-form label { display: grid; gap: 7px; color: #9ab4b8; font-size: 11px; }
.test-execution-toolbar select { min-width: 260px; }
.test-execution-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 18px; }
.test-execution-panel { padding: 22px; border: 1px solid rgb(104 221 211 / 14%); background: rgb(7 20 34 / 82%); box-shadow: 0 16px 40px rgb(0 0 0 / 16%); }
.test-execution-panel header { margin-bottom: 18px; }.test-execution-panel h2 { margin: 5px 0 0; color: #e7fffb; }.test-execution-panel header > span { color: #67dace; font: 11px ui-monospace, monospace; }.panel-kicker { margin: 0; color: #55dacc; font: 10px ui-monospace, monospace; letter-spacing: .16em; }
.test-case-list, .run-list { display: grid; gap: 8px; }.test-case-item { display: flex; align-items: flex-start; gap: 10px; padding: 12px; border: 1px solid rgb(104 221 211 / 10%); background: rgb(3 16 27 / 65%); cursor: pointer; }.test-case-item.selected { border-color: rgb(83 231 218 / 40%); background: rgb(36 212 194 / 10%); }.test-case-item input { margin-top: 3px; accent-color: #50e2d3; }.test-case-item span, .run-item > div:first-child { display: grid; gap: 5px; min-width: 0; }.test-case-item b, .run-item b { color: #d5ece9; font-size: 12px; }.test-case-item small, .run-item small { color: #78939a; font-size: 11px; overflow-wrap: anywhere; }
.test-execution-form { display: grid; gap: 12px; margin-top: 20px; padding-top: 18px; border-top: 1px solid rgb(104 221 211 / 12%); }.test-execution-form h3 { margin: 0; color: #cae8e4; font-size: 14px; }.test-execution-form input, .test-execution-form textarea, .test-execution-form select, .test-execution-toolbar select { box-sizing: border-box; width: 100%; padding: 9px 10px; border: 1px solid rgb(104 221 211 / 18%); border-radius: 4px; color: #dffaf7; background: rgb(2 13 25 / 88%); }.test-execution-form-row { display: grid; grid-template-columns: .8fr 1.2fr; gap: 10px; }.test-execution-form textarea { resize: vertical; font: 11px/1.5 ui-monospace, monospace; }.test-execution-form--top { margin-top: 0; padding-top: 0; border-top: 0; }
.test-execution-empty { color: #718a91; font-size: 12px; line-height: 1.7; }.test-execution-notice, .test-execution-error { margin: 14px 0; padding: 11px 14px; color: #91b5b7; border: 1px solid rgb(104 221 211 / 14%); background: rgb(8 30 39 / 60%); font-size: 12px; line-height: 1.6; }.test-execution-error { color: #ffb2ad; border-color: rgb(255 117 106 / 24%); background: rgb(74 22 31 / 42%); }.run-item { align-items: flex-start; flex-wrap: wrap; padding: 14px; border-top: 1px solid rgb(104 221 211 / 10%); }.run-item-actions { margin-left: auto; }.run-status { font-size: 11px; }.run-status--completed, .result-passed { color: #68e5ba; }.run-status--failed, .result-failed, .result-error { color: #ff938c; }.run-status--pending, .run-status--running, .result-skipped { color: #edc779; }.run-error { color: #ffaaa1 !important; }.run-results { display: flex; width: 100%; flex-wrap: wrap; gap: 8px; padding-top: 8px; color: #90aeb0; font-size: 11px; }.run-results span { padding: 4px 7px; border: 1px solid rgb(104 221 211 / 12%); }
@media (max-width: 850px) { .test-execution-grid { grid-template-columns: 1fr; } } @media (max-width: 560px) { .test-execution-toolbar { align-items: stretch; flex-direction: column; }.test-execution-toolbar select { min-width: 0; }.test-execution-form-row { grid-template-columns: 1fr; } }
</style>
