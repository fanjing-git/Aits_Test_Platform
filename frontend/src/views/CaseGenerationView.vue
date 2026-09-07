<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'
import { listProjects } from '../api/projects'
import { listRequirementDocuments } from '../api/requirements'
import { generateCaseRecord, listCaseGenerations, listCaseGenerationModelOptions, reviewCaseRecord, selectCaseRecord } from '../api/caseGeneration'

const projects = ref([])
const documents = ref([])
const records = ref([])
const selectedProject = ref('')
const selectedRecord = ref(null)
const selectedDocument = ref('')
const generationOptions = ref({ models: [] })
const reviewOptions = ref({ models: [] })
const generationModel = ref('')
const reviewModel = ref('')
const visibleCases = ref(100)
const loading = ref(true)
const optionsLoading = ref(false)
const busy = ref(false)
const error = ref('')
const notice = ref('')

const canWrite = computed(() => ['admin', 'platform_admin', 'owner', 'manager'].includes(projects.value.find(item => item.id === selectedProject.value)?.current_role))
const analyzedDocuments = computed(() => documents.value.filter(item => item.latest_analysis))
const reviewDone = computed(() => Number(selectedRecord.value?.review_rounds || 0) >= 5 && Boolean(selectedRecord.value?.review_report?.analysis_method))
const selectionDone = computed(() => Boolean(selectedRecord.value?.coverage_report?.automation_selection))
const shownCases = computed(() => (selectedRecord.value?.cases || []).slice(0, visibleCases.value))
const hasMoreCases = computed(() => shownCases.value.length < (selectedRecord.value?.cases?.length || 0))

function explain(err, fallback) {
  if (err.response?.status === 401) return '登录已过期，请重新登录。'
  if (err.response?.status === 403) return '当前账号没有执行此操作的权限。'
  const data = err.response?.data
  if (typeof data?.detail === 'string') return data.detail
  const first = data && Object.values(data)[0]
  return Array.isArray(first) ? first[0] : (typeof first === 'string' ? first : fallback)
}

async function loadModelOptions() {
  optionsLoading.value = true
  try {
    const [generation, review] = await Promise.all([
      listCaseGenerationModelOptions('case_generation'),
      listCaseGenerationModelOptions('case_review'),
    ])
    generationOptions.value = generation
    reviewOptions.value = review
  } catch (err) {
    generationOptions.value = { models: [], route_error: explain(err, '用例模型选项加载失败，请重试。') }
    reviewOptions.value = generationOptions.value
  } finally { optionsLoading.value = false }
}

async function load() {
  loading.value = true; error.value = ''
  try {
    projects.value = await listProjects()
    if (!selectedProject.value && projects.value.length) selectedProject.value = projects.value[0].id
    if (selectedProject.value) {
      [documents.value, records.value] = await Promise.all([listRequirementDocuments(selectedProject.value), listCaseGenerations(selectedProject.value)])
    } else { documents.value = []; records.value = [] }
    selectedRecord.value = records.value.find(item => item.id === selectedRecord.value?.id) || records.value[0] || null
    if (!selectedDocument.value) selectedDocument.value = analyzedDocuments.value[0]?.id || ''
    visibleCases.value = 100
    await loadModelOptions()
  } catch (err) { error.value = explain(err, '用例生成数据加载失败，请重试。') } finally { loading.value = false }
}

async function changeProject() { selectedDocument.value = ''; selectedRecord.value = null; generationModel.value = ''; reviewModel.value = ''; await load() }
function selectRecord(record) { selectedRecord.value = record; selectedDocument.value = record.document; visibleCases.value = 100 }
function roundStage(stage) { return { model_incremental: '模型递进分析', deterministic_fallback: '确定性补充（模型失败）', deterministic_baseline: '确定性基线（未配置模型）' }[stage] || stage || '未记录阶段' }
function roundTotal(round, index) { return Number.isFinite(Number(round.total)) ? Number(round.total) : (index === 4 ? selectedRecord.value?.total_cases || 0 : '未记录') }

async function runGenerate() {
  busy.value = true; error.value = ''; notice.value = ''
  try { const result = await generateCaseRecord(selectedRecord.value?.document || selectedDocument.value, generationModel.value); notice.value = '五轮递进用例生成完成。'; await load(); selectedRecord.value = records.value.find(item => item.id === result.id) || result } catch (err) { error.value = explain(err, '用例生成失败，请检查模型配置后重试。') } finally { busy.value = false }
}
async function runReview() {
  busy.value = true; error.value = ''; notice.value = ''
  try { const result = await reviewCaseRecord(selectedRecord.value.id, reviewModel.value); notice.value = '五轮用例评审完成。'; await load(); selectedRecord.value = records.value.find(item => item.id === result.id) || result } catch (err) { error.value = explain(err, '用例评审失败，请检查模型配置后重试。') } finally { busy.value = false }
}
async function runSelect() {
  busy.value = true; error.value = ''; notice.value = ''
  try { const result = await selectCaseRecord(selectedRecord.value.id); notice.value = '自动化筛选完成。'; await load(); selectedRecord.value = records.value.find(item => item.id === result.id) || result } catch (err) { error.value = explain(err, '自动化筛选失败，请重试。') } finally { busy.value = false }
}
watch(selectedRecord, () => { visibleCases.value = 100 })
onMounted(load)
</script>

<template>
  <WorkspaceShell active="case-generation"><div class="workspace-content case-generation-page">
    <div class="page-title-row"><div><p class="workspace-eyebrow">CASE GENERATION</p><h1>用例生成</h1><p class="workspace-lead">基于需求深度分析结果，五轮递进补充测试覆盖，再进行评审与自动化筛选。</p></div></div>
    <div v-if="notice" class="case-generation-notice" role="status">{{ notice }}</div><div v-if="error" class="case-generation-error" role="alert">{{ error }} <button class="text-action" @click="load">重新加载</button></div>
    <div class="case-generation-toolbar"><label>项目<select v-model="selectedProject" @change="changeProject"><option v-for="item in projects" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><button class="secondary-action" @click="load">刷新</button></div>
    <section v-if="loading" class="state-panel"><span class="loading-ring"></span><b>正在加载用例生成数据</b></section>
    <section v-else class="case-generation-layout"><aside class="case-generation-panel"><div class="case-generation-heading"><h2>生成记录</h2><span>{{ records.length }}</span></div><div v-if="!records.length" class="case-generation-empty">暂无生成记录，请选择已完成分析的需求文档生成用例。</div><button v-for="item in records" :key="item.id" class="case-generation-record" :class="{ active: item.id === selectedRecord?.id }" @click="selectRecord(item)"><b>{{ item.document_title }}</b><small>{{ item.status }} · {{ item.total_cases }} 条</small></button></aside>
      <main class="case-generation-panel"><div v-if="!selectedRecord" class="case-generation-empty"><h2>生成测试用例</h2><p>选择已完成需求分析的文档后开始。</p><select v-model="selectedDocument"><option value="">请选择需求文档</option><option v-for="item in analyzedDocuments" :key="item.id" :value="item.id">{{ item.title }} v{{ item.version }}</option></select><label class="model-choice-label">用例生成模型<select v-model="generationModel" :disabled="optionsLoading || busy"><option value="">继承平台或功能默认</option><option v-for="model in generationOptions.models" :key="model.id" :value="String(model.id)">{{ model.name }} · {{ model.model_name }}（{{ model.model_type_label }}）</option></select></label><small v-if="generationOptions.effective_model" class="model-choice-hint">当前生效：{{ generationOptions.effective_model.name }} · {{ generationOptions.effective_model.model_name }}</small><button class="primary-action" :disabled="busy || !canWrite || !selectedDocument" @click="runGenerate">{{ busy ? '生成中…' : '生成用例' }}</button><p v-if="!analyzedDocuments.length" class="case-generation-hint">当前项目没有已完成需求分析的文档。</p></div><template v-else><div class="case-generation-heading"><div><h2>{{ selectedRecord.document_title }}</h2><small>生成 {{ selectedRecord.rounds }} 轮 · {{ selectedRecord.status }}</small></div><div class="case-generation-actions"><button class="secondary-action" :disabled="busy || !canWrite" @click="runGenerate">重新生成</button><button class="secondary-action" :disabled="busy || !canWrite || reviewDone" @click="runReview">{{ reviewDone ? '已评审' : '评审' }}</button><button class="secondary-action" :disabled="busy || !canWrite || selectionDone" @click="runSelect">{{ selectionDone ? '已筛选' : '自动化筛选' }}</button></div></div><div class="case-generation-model-bar"><label>用例生成模型<select v-model="generationModel" :disabled="optionsLoading || busy"><option value="">继承平台或功能默认</option><option v-for="model in generationOptions.models" :key="model.id" :value="String(model.id)">{{ model.name }} · {{ model.model_name }}</option></select></label><label>用例评审模型<select v-model="reviewModel" :disabled="optionsLoading || busy"><option value="">继承平台或功能默认</option><option v-for="model in reviewOptions.models" :key="model.id" :value="String(model.id)">{{ model.name }} · {{ model.model_name }}</option></select></label></div><div class="case-generation-summary"><span>总用例 {{ selectedRecord.total_cases }}</span><span>自动化 {{ selectedRecord.auto_cases }}</span><span>手工 {{ selectedRecord.manual_cases }}</span><span>覆盖度 {{ Math.round((selectedRecord.coverage_report?.coverage_rate || 0) * 100) }}%</span></div><div v-if="selectedRecord.coverage_report?.round_trace?.length" class="case-generation-review"><b>五轮递进生成</b><ul><li v-for="(round, index) in selectedRecord.coverage_report.round_trace" :key="round.round">第 {{ round.round }} 轮：{{ roundStage(round.stage) }}，新增 {{ round.added ?? 0 }} 条，累计 {{ roundTotal(round, index) }} 条</li></ul><p v-if="selectedRecord.coverage_report.model_warning" class="case-generation-error">部分轮次未能调用模型，已按记录的策略处理：{{ selectedRecord.coverage_report.model_warning }}</p></div><div v-if="selectedRecord.review_report?.analysis_method" class="case-generation-review"><b>评审方式：{{ selectedRecord.review_report.analysis_method === 'model_verified' ? '模型复核' : '确定性基线' }}</b><span v-if="selectedRecord.review_report.issue_count !== undefined">问题 {{ selectedRecord.review_report.issue_count }} 条</span><p v-if="selectedRecord.review_report.model_warning" class="case-generation-error">模型评审未完成：{{ selectedRecord.review_report.model_warning }}</p><ul v-if="selectedRecord.review_report.issues?.length"><li v-for="(issue, index) in selectedRecord.review_report.issues" :key="issue.id || `review-issue-${index}`">【{{ issue.severity_label || ({ high: '高', medium: '中', low: '低' }[issue.severity] || '中') }}】{{ issue.description }} · {{ issue.suggestion }}</li></ul></div><p v-if="selectedRecord.review_report?.approved === false" class="case-generation-error">评审未通过，请根据问题修正后重新生成。</p><div v-if="!selectedRecord.cases?.length" class="case-generation-empty">当前记录没有可展示的用例。</div><template v-else><table class="case-generation-table"><thead><tr><th>编号</th><th>标题</th><th>类型</th><th>优先级</th><th>自动化</th><th>预期结果</th></tr></thead><tbody><tr v-for="item in shownCases" :key="item.id"><td>{{ item.id }}</td><td>{{ item.title }}</td><td>{{ item.type }}</td><td>{{ item.priority }}</td><td>{{ item.automatable ? '建议自动化' : '建议手工' }}</td><td>{{ item.expected_result }}</td></tr></tbody></table><button v-if="hasMoreCases" class="secondary-action case-generation-more" @click="visibleCases += 100">加载更多（已显示 {{ shownCases.length }} / {{ selectedRecord.cases.length }}）</button></template></template></main>
    </section>
  </div></WorkspaceShell>
</template>
