<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'
import { listProjects } from '../api/projects'
import { listRequirementDocuments } from '../api/requirements'
import { cancelCaseGeneration, deleteCaseGeneration, generateCaseRecord, getCaseGeneration, listCaseGenerations, listCaseGenerationModelOptions, reviewCaseRecord, saveReviewedCases, selectCaseRecord } from '../api/caseGeneration'
import { getSkillChainRun } from '../api/skills'

const projects = ref([])
const documents = ref([])
const records = ref([])
const selectedProject = ref('')
const selectedRecord = ref(null)
const selectedDocument = ref('')
const selectedApprovedTestPointIds = ref([])
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
const skillExecution = ref(null)
const busyMessage = ref('')
const busyStartedAt = ref(0)
const busySeconds = ref(0)
const lastOperation = ref('')
const reviewEditing = ref(false)
const reviewDraftCases = ref([])
const newReviewCases = ref([])
const activeReviewCaseKey = ref('')
const reviewSaving = ref(false)
const deletingRecordId = ref('')
const caseFilter = ref('all')
const reviewEditScope = ref('llm_issues')
const reviewEditFunctionId = ref('all')
const manualConfirmedCaseIds = ref([])
let busyTimer = null
let recordRefreshTimer = null
const route = useRoute()

const canWrite = computed(() => ['admin', 'platform_admin', 'owner', 'manager'].includes(projects.value.find(item => item.id === selectedProject.value)?.current_role))
const skillStatusText = { completed: '已完成', failed: '失败', needs_input: '等待补充' }
const analyzedDocuments = computed(() => documents.value.filter(item => item.latest_analysis))
function isManualReviewComplete(analysis) {
  return Boolean(analysis?.manual_review_complete ?? (analysis?.quality_status === 'complete' && analysis?.coverage_report?.manual_confirmation?.confirmed === true))
}
function isGenerationAllowed(analysis) {
  return Boolean(analysis?.generation_allowed ?? isManualReviewComplete(analysis))
}
const blockedDocuments = computed(() => documents.value.filter(item => item.latest_analysis && !isGenerationAllowed(item.latest_analysis)))
const selectedAnalysisDocument = computed(() => documents.value.find(item => item.id === selectedDocument.value))
const approvedTestPoints = computed(() => {
  const analysis = selectedAnalysisDocument.value?.latest_analysis
  const approved = new Set((analysis?.coverage_report?.manual_confirmation?.reviewed_test_point_ids || []).map(String))
  const ids = approved.size || analysis?.quality_status !== 'complete' ? approved : new Set((analysis?.test_points || []).map(item => String(item.id)))
  return (analysis?.test_points || []).filter(item => ids.has(String(item.id)))
})
const reviewCompleted = computed(() => Number(selectedRecord.value?.review_rounds || 0) >= 5 && Boolean(selectedRecord.value?.review_report?.analysis_method) && selectedRecord.value?.review_report?.execution_status !== 'failed')
const reviewSkipped = computed(() => selectedRecord.value?.review_report?.execution_status === 'skipped' && selectedRecord.value?.review_report?.skipped === true)
const reviewApproved = computed(() => reviewCompleted.value && selectedRecord.value?.review_report?.approved === true)
const reviewStatusLabel = computed(() => reviewSkipped.value ? '暂无用例可评审' : (!reviewCompleted.value ? '未评审' : (reviewApproved.value ? '评审通过' : '评审未通过')))
const generateButtonLabel = computed(() => busy.value && lastOperation.value === 'generate' ? '生成中…' : '重新生成')
const reviewButtonLabel = computed(() => {
  if (busy.value && lastOperation.value === 'review' || selectedRecord.value?.status === 'reviewing' && Boolean(selectedRecord.value?.cases?.length)) return '评审中…'
  if (isEmptyGenerationShell(selectedRecord.value)) return '暂无用例'
  if (selectedRecord.value?.status === 'generating') return '等待生成…'
  if (reviewSkipped.value || !selectedRecord.value?.cases?.length) return '暂无用例'
  return reviewApproved.value ? '已评审通过' : (reviewCompleted.value ? '评审未通过' : '评审')
})
const selectButtonLabel = computed(() => busy.value && lastOperation.value === 'select' ? '筛选中…' : (selectionDone.value ? '已筛选' : '自动化筛选'))
const manualRevision = computed(() => selectedRecord.value?.review_report?.manual_revision || null)
const activeReviewCase = computed(() => {
  if (activeReviewCaseKey.value.startsWith('new:')) return newReviewCases.value.find(item => item._key === activeReviewCaseKey.value.slice(4)) || null
  return reviewDraftCases.value.find(item => item.id === activeReviewCaseKey.value) || null
})
const activeReviewIssues = computed(() => (selectedRecord.value?.review_report?.issues || []).filter(item => String(item.case_id || '') === String(activeReviewCase.value?.id || '')))
const selectionDone = computed(() => Boolean(selectedRecord.value?.coverage_report?.automation_selection))
const reviewIssueCaseIds = computed(() => new Set((selectedRecord.value?.review_report?.issues || []).map(item => String(item.case_id || '').trim()).filter(Boolean)))
function caseReviewStatus(item) {
  if (item?.manual_review_status === 'manual_final') return 'manual_final'
  if (reviewIssueCaseIds.value.has(String(item?.id || '')) && (reviewCompleted.value || manualRevision.value?.status === 'saved_pending_review')) return 'pending_review'
  if (reviewApproved.value) return 'reviewed'
  if (reviewCompleted.value) return 'auto_passed'
  return 'generated'
}
function caseStatusLabel(item) { return { manual_final: '人工修订用例', pending_review: '待评审', reviewed: '评审通过', auto_passed: '无需人工评审', generated: '已生成' }[caseReviewStatus(item)] }
function caseFunctionLabel(item) {
  const functions = selectedAnalysisDocument.value?.latest_analysis?.functions || []
  const functionItem = functions.find(candidate => String(candidate.id) === String(item?.source_function_id))
  return functionItem?.name || functionItem?.description || item?.source_function_id || '未关联功能点'
}
const filteredCases = computed(() => {
  const cases = [...(selectedRecord.value?.cases || [])]
  const visible = caseFilter.value === 'all'
    ? cases
    : cases.filter(item => caseFilter.value === 'final'
      ? ['reviewed', 'manual_final'].includes(caseReviewStatus(item))
      : caseReviewStatus(item) === caseFilter.value)
  return visible.sort((left, right) => `${caseFunctionLabel(left)}-${left.id}`.localeCompare(`${caseFunctionLabel(right)}-${right.id}`, 'zh-CN'))
})
const reviewScopeCases = computed(() => reviewDraftCases.value.filter(item => {
  const status = caseReviewStatus(item)
  const manuallyConfirmed = item?.manual_review_status === 'manual_final'
  return reviewEditScope.value === 'all'
    || (reviewEditScope.value === 'llm_issues'
      ? reviewIssueCaseIds.value.has(String(item?.id || '')) && !manuallyConfirmed
      : (reviewEditScope.value === 'pending_review'
        ? status === 'pending_review' && !manuallyConfirmed
      : (reviewEditScope.value === 'final' ? ['reviewed', 'manual_final'].includes(status) : status === reviewEditScope.value))
      )
}))
const reviewEditFunctionOptions = computed(() => {
  const functions = selectedAnalysisDocument.value?.latest_analysis?.functions || []
  const scopeFunctionIds = new Set(reviewScopeCases.value.map(item => String(item?.source_function_id || '')).filter(Boolean))
  return functions.filter(item => scopeFunctionIds.has(String(item.id)))
})
const reviewEditScopeCounts = computed(() => {
  const cases = reviewDraftCases.value
  return {
    llm_issues: cases.filter(item => reviewIssueCaseIds.value.has(String(item?.id || '')) && item?.manual_review_status !== 'manual_final').length,
    pending_review: cases.filter(item => caseReviewStatus(item) === 'pending_review' && item?.manual_review_status !== 'manual_final').length,
    all: cases.length,
    final: cases.filter(item => ['reviewed', 'manual_final'].includes(caseReviewStatus(item))).length,
    generated: cases.filter(item => caseReviewStatus(item) === 'generated').length,
  }
})
const filteredReviewDraftCases = computed(() => reviewScopeCases.value.filter(item => {
  const functionMatch = reviewEditFunctionId.value === 'all' || String(item.source_function_id || '') === String(reviewEditFunctionId.value)
  return functionMatch
}))
const caseCounts = computed(() => {
  const cases = selectedRecord.value?.cases || []
  return { all: cases.length, pending_review: cases.filter(item => caseReviewStatus(item) === 'pending_review').length, final: cases.filter(item => ['reviewed', 'manual_final'].includes(caseReviewStatus(item))).length, auto_passed: cases.filter(item => caseReviewStatus(item) === 'auto_passed').length, generated: cases.filter(item => caseReviewStatus(item) === 'generated').length }
})
const shownCases = computed(() => filteredCases.value.slice(0, visibleCases.value))
const hasMoreCases = computed(() => shownCases.value.length < filteredCases.value.length)
const hasStructuredGeneration = computed(() => (selectedRecord.value?.coverage_report?.round_trace || []).some(round => round.structured_generation))
function recordStatusText(item) {
  if (isEmptyGenerationShell(item)) return '未生成'
  if (item?.status === 'failed' && !item?.cases?.length && !item?.rounds) return '未生成'
  return { generating: '生成中', reviewing: '评审中', completed: '已完成', failed: '失败' }[item?.status] || item?.status || '未开始'
}
function isEmptyGenerationShell(item) { return item?.status === 'generating' && !item?.cases?.length && !item?.rounds && !item?.total_cases && !Object.keys(item?.coverage_report || {}).length }
function activeTaskForRecord(record) {
  const candidates = [record?.coverage_report?.task_runtime, record?.review_report?.task_runtime]
  return candidates.find(item => ['pending', 'running', 'cancel_requested'].includes(item?.status)) || null
}
const activeTaskRuntime = computed(() => activeTaskForRecord(selectedRecord.value))
const taskStatusText = { pending: '排队中', running: '执行中', cancel_requested: '取消中', completed: '已完成', failed: '失败', cancelled: '已取消', timed_out: '已超时' }
const recordProcessing = computed(() => Boolean(activeTaskRuntime.value) || (selectedRecord.value?.status === 'generating' && !isEmptyGenerationShell(selectedRecord.value)) || (selectedRecord.value?.status === 'reviewing' && Boolean(selectedRecord.value?.cases?.length)))
const recordStatusLabel = computed(() => recordStatusText(selectedRecord.value))
const reviewIssueSummary = computed(() => {
  const issues = selectedRecord.value?.review_report?.issues || []
  return {
    high: issues.filter(item => item.severity === 'high').length,
    medium: issues.filter(item => item.severity === 'medium').length,
    low: issues.filter(item => item.severity === 'low').length,
  }
})
const designMethodLabels = {
  positive_flow: '正向流程',
  equivalence_class: '等价类',
  boundary_value: '边界值',
  error_guessing: '错误猜测法',
  cause_effect_graph: '因果图',
  state_transition: '状态转换',
  security: '安全',
  performance: '性能',
  linkage: '联动',
  regression_compatibility: '回归兼容',
}
const coverageMetricConfig = {
  evidence: { label: '证据覆盖率', legacyKey: 'evidence_coverage_rate' },
  function: { label: '功能点覆盖率', legacyKey: 'function_coverage_rate' },
  test_dimension: { label: '测试维度覆盖率', legacyKey: 'test_dimension_coverage_rate' },
  linkage: { label: '联动覆盖率', legacyKey: 'linkage_coverage_rate' },
}

function explain(err, fallback) {
  if (err.response?.status === 401) return '登录已过期，请重新登录。'
  if (err.response?.status === 403) return '当前账号没有执行此操作的权限。'
  if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') return '结构化用例处理等待时间过长，后端可能仍在处理；请刷新页面查看是否已保存部分结果，或稍后重试。'
  const data = err.response?.data
  if (typeof data?.detail === 'string') return data.detail
  const first = data && Object.values(data)[0]
  return Array.isArray(first) ? first[0] : (typeof first === 'string' ? first : fallback)
}

function beginBusy(label, operation) {
  busy.value = true
  busyMessage.value = label
  lastOperation.value = operation
  busyStartedAt.value = Date.now()
  busySeconds.value = 0
  if (busyTimer) clearInterval(busyTimer)
  busyTimer = setInterval(() => { busySeconds.value = Math.floor((Date.now() - busyStartedAt.value) / 1000) }, 1000)
}

function qualityLabel(status, analysis) {
  if (status === 'complete' && !isManualReviewComplete(analysis)) return '分析完成·待人工确认'
  return { complete: '已确认可生成', needs_review: '待人工确认', partial: '部分完成', failed: '分析失败' }[status] || '未完成'
}
function qualityReason(document) { return document?.latest_analysis?.coverage_report?.quality_reason || '当前分析结果需要先完成完整性确认。' }
function designMethodLabel(item) {
  return item?.test_design_method_label || designMethodLabels[item?.test_design_method] || ({ positive: '正向流程', negative: '错误猜测法', boundary: '边界值', linkage: '联动' }[item?.type] || item?.type || '未分类')
}
function issueSeverityLabel(issue) { return issue?.severity_label || ({ high: '高', medium: '中', low: '低' }[issue?.severity] || '中') }
function issueDimensionLabel(issue) { return issue?.dimension || issue?.code || '通用质量检查' }
function coverageMetric(report, key) {
  const metric = report?.coverage_metrics?.[key]
  if (metric && Object.prototype.hasOwnProperty.call(metric, 'rate')) return metric
  const config = coverageMetricConfig[key]
  const legacyRate = config ? (report?.[config.legacyKey] ?? (key === 'evidence' ? report?.evidence_coverage?.coverage_ratio : null)) : null
  return legacyRate === null || legacyRate === undefined ? null : { rate: legacyRate }
}
function coverageMetricText(report, key) {
  const rate = coverageMetric(report, key)?.rate
  return rate === null || rate === undefined ? '待计算' : `${Math.round(Number(rate) * 100)}%`
}
function coverageMetricCount(report, key) {
  const metric = coverageMetric(report, key)
  return metric?.covered_count !== undefined && metric?.total_count !== undefined ? `${metric.covered_count}/${metric.total_count}` : ''
}
function coverageMetricLabel(key) { return coverageMetricConfig[key]?.label || key }
function reviewComparable(item) { return { title: item.title || '', steps: item.steps || [], expected_result: item.expected_result || '', priority: item.priority || '', automatable: Boolean(item.automatable), type: item.type || '', test_design_method: item.test_design_method || '' } }
function reviewDraft(item) { return { ...item, steps_text: (item.steps || []).join('\n'), _original: JSON.stringify(reviewComparable(item)) } }
function newReviewDraft() { return { _key: `new-${Date.now()}-${Math.random().toString(16).slice(2)}`, title: '', steps_text: '', expected_result: '', priority: 'P1', automatable: false, type: 'positive', test_design_method: 'positive_flow', source_function_id: selectedAnalysisDocument.value?.latest_analysis?.functions?.[0]?.id || '' } }
function beginReviewEditing() { reviewDraftCases.value = (selectedRecord.value?.cases || []).map(reviewDraft); newReviewCases.value = []; manualConfirmedCaseIds.value = []; reviewEditScope.value = 'llm_issues'; reviewEditFunctionId.value = 'all'; activeReviewCaseKey.value = ''; reviewEditing.value = true; requestAnimationFrame(() => { activeReviewCaseKey.value = filteredReviewDraftCases.value[0]?.id || '' }) }
function cancelReviewEditing() { reviewEditing.value = false; reviewDraftCases.value = []; newReviewCases.value = []; manualConfirmedCaseIds.value = []; activeReviewCaseKey.value = '' }
function addReviewCaseDraft() { const item = newReviewDraft(); newReviewCases.value.push(item); activeReviewCaseKey.value = `new:${item._key}` }
function removeReviewCaseDraft(key) { newReviewCases.value = newReviewCases.value.filter(item => item._key !== key); if (activeReviewCaseKey.value === `new:${key}`) activeReviewCaseKey.value = reviewDraftCases.value[0]?.id || '' }
function reviewPayload(item) { return { id: item.id, title: item.title, steps: item.steps_text.split('\n').map(value => value.trim()).filter(Boolean), expected_result: item.expected_result, priority: item.priority, automatable: item.automatable, type: item.type, test_design_method: item.test_design_method, source_function_id: item.source_function_id } }
function confirmActiveCase() {
  const caseId = activeReviewCase.value?.id
  if (!caseId || manualConfirmedCaseIds.value.includes(caseId)) return
  manualConfirmedCaseIds.value.push(caseId)
}
function isManualConfirmed(item) { return manualConfirmedCaseIds.value.includes(item?.id) || item?.manual_review_status === 'manual_final' }
async function saveManualReviewCases() {
  const changed = reviewDraftCases.value.filter(item => JSON.stringify(reviewComparable({ ...item, steps: item.steps_text.split('\n').map(value => value.trim()).filter(Boolean) })) !== item._original)
  const updates = [...changed.map(reviewPayload), ...reviewDraftCases.value.filter(item => manualConfirmedCaseIds.value.includes(item.id) && !changed.some(candidate => candidate.id === item.id)).map(item => ({ id: item.id }))]
  const additions = newReviewCases.value.map(item => ({ title: item.title, steps: item.steps_text.split('\n').map(value => value.trim()).filter(Boolean), expected_result: item.expected_result, priority: item.priority, automatable: item.automatable, type: item.type, test_design_method: item.test_design_method, source_function_id: item.source_function_id }))
  if (!updates.length && !additions.length) { error.value = '请先修改用例或新增用例，再保存人工评审结果。'; return }
  if (!window.confirm('确认保存人工评审结果？修订或确认的用例会加入最终用例列表，并需要重新评审。')) return
  reviewSaving.value = true; error.value = ''; notice.value = ''
  try {
    const result = await saveReviewedCases(selectedRecord.value.id, { cases: updates, new_cases: additions })
    selectedRecord.value = result
    records.value = records.value.map(item => item.id === result.id ? result : item)
    cancelReviewEditing()
    notice.value = `人工修订已保存，当前共 ${result.total_cases} 条用例；请点击“评审”重新确认。`
  } catch (err) { error.value = explain(err, '人工修订保存失败，请检查内容后重试。') } finally { reviewSaving.value = false }
}

function endBusy() {
  busy.value = false
  if (busyTimer) clearInterval(busyTimer)
  busyTimer = null
}

async function refreshProcessingRecord() {
  const projectId = selectedProject.value
  const recordId = selectedRecord.value?.id
  if (!projectId || !recordId || !recordProcessing.value) return
  try {
    const latest = await getCaseGeneration(recordId)
    records.value = records.value.map(item => item.id === recordId ? latest : item)
    selectedRecord.value = latest
  } catch (err) {
    // 后台轮询失败时保留当前页面状态，避免把短暂网络抖动误报成业务失败。
  } finally {
    scheduleRecordRefresh()
  }
}

async function waitForCaseTask(initialRecord) {
  let latest = initialRecord
  if (!activeTaskForRecord(latest)) return latest
  selectedRecord.value = latest
  for (let attempt = 0; attempt < 1200; attempt += 1) {
    await new Promise(resolve => window.setTimeout(resolve, 1500))
    latest = await getCaseGeneration(initialRecord.id)
    records.value = records.value.map(item => item.id === latest.id ? latest : item)
    selectedRecord.value = latest
    const runtime = activeTaskForRecord(latest) || latest.coverage_report?.task_runtime || latest.review_report?.task_runtime
    if (!['pending', 'running', 'cancel_requested'].includes(runtime?.status)) {
      const runId = latest.generation_run || latest.review_run
      if (runId) {
        const run = await getSkillChainRun(runId)
        skillExecution.value = { ...skillExecution.value, status: run.status, run_id: run.id, message: run.status === 'completed' ? '真实业务产物已写入记录' : (run.error_message || '父运行已保存') }
      }
      if (['failed', 'cancelled', 'timed_out'].includes(runtime?.status)) throw new Error(`后台任务${taskStatusText[runtime.status] || '未完成'}：${runtime.error_code || '请查看任务详情后重试。'}`)
      return latest
    }
  }
  throw new Error('后台任务等待超过30分钟，请刷新页面查看最终状态。')
}

async function cancelActiveCaseTask() {
  if (!selectedRecord.value || !activeTaskRuntime.value || !canWrite.value) return
  try {
    const result = await cancelCaseGeneration(selectedRecord.value.id)
    selectedRecord.value = result
    records.value = records.value.map(item => item.id === result.id ? result : item)
    notice.value = '已提交取消请求，后台会在当前安全检查点停止。'
  } catch (err) { error.value = explain(err, '取消后台任务失败，请稍后重试。') }
}

function scheduleRecordRefresh() {
  if (recordRefreshTimer) clearTimeout(recordRefreshTimer)
  recordRefreshTimer = null
  if (!recordProcessing.value) return
  recordRefreshTimer = setTimeout(refreshProcessingRecord, 3000)
}

async function retryOperation() {
  if (lastOperation.value === 'generate') return runGenerate()
  if (lastOperation.value === 'review') return runReview()
  if (lastOperation.value === 'select') return runSelect()
  return load()
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
    const routeRecordId = String(route.query.record || '')
    const routeDocumentId = String(route.query.document || '')
    selectedRecord.value = records.value.find(item => item.id === routeRecordId)
      || records.value.find(item => item.id === selectedRecord.value?.id)
      || records.value[0]
      || null
    if (!analyzedDocuments.value.some(item => item.id === selectedDocument.value) || routeDocumentId) selectedDocument.value = routeDocumentId || selectedRecord.value?.document || analyzedDocuments.value[0]?.id || ''
    syncApprovedTestPointSelection()
    visibleCases.value = 100
    await loadModelOptions()
    scheduleRecordRefresh()
  } catch (err) { error.value = explain(err, '用例生成数据加载失败，请重试。') } finally { loading.value = false }
}

async function changeProject() { selectedDocument.value = ''; selectedRecord.value = null; generationModel.value = ''; reviewModel.value = ''; await load() }
function selectRecord(record) { selectedRecord.value = record; selectedDocument.value = record.document; visibleCases.value = 100; syncApprovedTestPointSelection() }
function recordCanDelete(record) { return !['generating', 'reviewing'].includes(record?.status) }
async function deleteRecord(record) {
  if (!recordCanDelete(record)) { notice.value = '当前记录正在处理中，完成后才能删除。'; return }
  if (!window.confirm(`确认删除“${record.document_title || '当前'}”这条用例生成记录？删除后不可恢复，但不会删除需求文档和分析结果。`)) return
  deletingRecordId.value = record.id; error.value = ''; notice.value = ''
  try {
    await deleteCaseGeneration(record.id)
    const wasSelected = selectedRecord.value?.id === record.id
    records.value = records.value.filter(item => item.id !== record.id)
    if (wasSelected) {
      cancelReviewEditing()
      selectedRecord.value = records.value[0] || null
      selectedDocument.value = selectedRecord.value?.document || selectedDocument.value
      syncApprovedTestPointSelection()
    }
    notice.value = '用例生成记录已删除。'
  } catch (err) { error.value = explain(err, '用例生成记录删除失败，请重试。') } finally { deletingRecordId.value = '' }
}
function syncApprovedTestPointSelection() { selectedApprovedTestPointIds.value = approvedTestPoints.value.map(item => String(item.id)) }
function roundStage(stage) { return { model_incremental: '模型递进分析', deterministic_fallback: '确定性补充（模型失败）', deterministic_baseline: '确定性基线（未配置模型）' }[stage] || stage || '未记录阶段' }
function roundTotal(round, index) { return Number.isFinite(Number(round.total)) ? Number(round.total) : (index === 4 ? selectedRecord.value?.total_cases || 0 : '未记录') }

async function runGenerateLegacy() {
  busy.value = true; error.value = ''; notice.value = ''
  try { const result = await generateCaseRecord(selectedRecord.value?.document || selectedDocument.value, generationModel.value, selectedApprovedTestPointIds.value); notice.value = '五轮递进用例生成完成。'; await load(); selectedRecord.value = records.value.find(item => item.id === result.id) || result } catch (err) { error.value = explain(err, '用例生成失败，请检查模型配置后重试。') } finally { busy.value = false }
}
async function runReviewLegacy() {
  busy.value = true; error.value = ''; notice.value = ''
  try { const result = await reviewCaseRecord(selectedRecord.value.id, reviewModel.value); notice.value = '五轮用例评审完成。'; await load(); selectedRecord.value = records.value.find(item => item.id === result.id) || result } catch (err) { error.value = explain(err, '用例评审失败，请检查模型配置后重试。') } finally { busy.value = false }
}
async function runSelectLegacy() {
  busy.value = true; error.value = ''; notice.value = ''
  try { const result = await selectCaseRecord(selectedRecord.value.id); notice.value = '自动化筛选完成。'; await load(); selectedRecord.value = records.value.find(item => item.id === result.id) || result } catch (err) { error.value = explain(err, '自动化筛选失败，请重试。') } finally { busy.value = false }
}
async function runGenerateWithStatus() {
  beginBusy('正在执行五轮用例生成，服务端会逐轮保存状态', 'generate'); error.value = ''; notice.value = ''
  try {
    const analysis = selectedAnalysisDocument.value?.latest_analysis
    const qualityStatus = analysis?.quality_status
    if (qualityStatus && !['complete', 'needs_review'].includes(qualityStatus)) {
      error.value = `当前分析为${qualityLabel(qualityStatus, analysis)}，请返回需求分析页重新执行。`
      return
    }
    if (!isGenerationAllowed(analysis)) {
      error.value = '需求分析已完成，但人工审核尚未完成；请先到需求智能分析页面完成全部审核并确认。'
      return
    }
    if (!selectedApprovedTestPointIds.value.length) {
      error.value = '当前没有已审核测试点，请先在需求分析页勾选测试点并点击“标记所选为已审核”。'
      return
    }
    const result = await generateCaseRecord(selectedRecord.value?.document || selectedDocument.value, generationModel.value, selectedApprovedTestPointIds.value)
    const generated = await waitForCaseTask(result)
    await load()
    selectedRecord.value = records.value.find(item => item.id === generated.id) || generated
    const generatedCount = selectedRecord.value?.total_cases || result.total_cases || 0
    if (!generatedCount || !selectedRecord.value?.cases?.length) {
      notice.value = '本次未生成用例，已跳过自动评审：暂无用例可评审。'
      return
    }
    beginBusy(`已生成 ${generatedCount} 条用例，正在继续执行五轮大模型评审`, 'review')
    try {
      const reviewed = await reviewCaseRecord(selectedRecord.value.id, reviewModel.value)
      const completedReview = await waitForCaseTask(reviewed)
      await load()
      selectedRecord.value = records.value.find(item => item.id === completedReview.id) || completedReview
      const issueCount = selectedRecord.value?.review_report?.issue_count ?? completedReview.review_report?.issue_count ?? 0
      notice.value = `重新生成完成：${generatedCount} 条用例已自动评审，发现 ${issueCount} 条问题。`
    } catch (reviewErr) {
      error.value = `用例已生成 ${generatedCount} 条，但自动评审失败：${explain(reviewErr, '请点击“评审”重试。')}`
    }
  } catch (err) { error.value = explain(err, '用例生成失败，请检查分析状态或模型配置后重试。') } finally { endBusy() }
}

async function runReviewWithStatus() {
  if (!selectedRecord.value?.cases?.length) { notice.value = '暂无用例可评审，已结束当前操作。'; return }
  beginBusy('正在执行五轮用例评审，正在等待模型或确定性基线完成', 'review'); error.value = ''; notice.value = ''
  try { const result = await reviewCaseRecord(selectedRecord.value.id, reviewModel.value); const reviewed = await waitForCaseTask(result); await load(); selectedRecord.value = records.value.find(item => item.id === reviewed.id) || reviewed; notice.value = `用例评审完成：发现 ${selectedRecord.value?.review_report?.issue_count ?? reviewed.review_report?.issue_count ?? 0} 条问题，当前状态为${reviewStatusLabel.value}。` } catch (err) { error.value = explain(err, '用例评审失败，请检查模型路由或重试。') } finally { endBusy() }
}

async function runSelectWithStatus() {
  beginBusy('正在计算自动化适配性', 'select'); error.value = ''; notice.value = ''
  try { const result = await selectCaseRecord(selectedRecord.value.id); await load(); selectedRecord.value = records.value.find(item => item.id === result.id) || result; notice.value = `自动化筛选完成：自动化 ${selectedRecord.value?.auto_cases || result.auto_cases || 0} 条，手工 ${selectedRecord.value?.manual_cases || result.manual_cases || 0} 条。` } catch (err) { error.value = explain(err, '自动化筛选失败，请重试。') } finally { endBusy() }
}

// Keep the template contract stable while routing all actions through the
// status-aware handlers above.
async function runGenerate() { return runGenerateWithStatus() }
async function runReview() { return runReviewWithStatus() }
async function runSelect() { return runSelectWithStatus() }

watch(selectedRecord, () => { visibleCases.value = 100; scheduleRecordRefresh() })
watch(selectedDocument, () => { syncApprovedTestPointSelection() })
watch(reviewEditScope, () => {
  if (reviewEditFunctionId.value !== 'all' && !reviewEditFunctionOptions.value.some(item => String(item.id) === String(reviewEditFunctionId.value))) reviewEditFunctionId.value = 'all'
})
watch([reviewEditScope, reviewEditFunctionId], () => { if (reviewEditing.value && !activeReviewCaseKey.value.startsWith('new:')) activeReviewCaseKey.value = filteredReviewDraftCases.value[0]?.id || '' })
onMounted(load)
onBeforeUnmount(() => { if (busyTimer) clearInterval(busyTimer); if (recordRefreshTimer) clearTimeout(recordRefreshTimer) })
</script>

<template>
  <WorkspaceShell active="case-generation"><div class="workspace-content case-generation-page">
    <div v-if="busy" class="case-generation-notice" role="status">{{ busyMessage }} · 已等待 {{ busySeconds }} 秒；长任务完成前请勿重复提交。</div>
    <div v-if="error" class="case-generation-error" role="alert">{{ error }} <button class="text-action" @click="retryOperation">重试当前操作</button><button class="text-action" @click="load">刷新页面</button></div>
    <div v-if="selectedRecord?.coverage_report?.round_trace?.length" class="case-generation-review" role="status"><b>执行证据</b><ul><li v-for="round in selectedRecord.coverage_report.round_trace" :key="`evidence-${round.round}`">第 {{ round.round }} 轮 · {{ round.status || 'completed' }} · 模型 {{ round.model_status || 'not_configured' }}<span v-if="round.model_route?.model"> · {{ round.model_route.model.name }} / {{ round.model_route.model.model_name }}</span><span v-if="round.model_error_code"> · 错误 {{ round.model_error_code }}</span></li></ul></div>
    <div v-if="selectedRecord?.review_report?.model_route_resolution" class="case-generation-review" role="status">评审路由：{{ selectedRecord.review_report.model_route_resolution.effective_source || '未配置模型' }}<span v-if="selectedRecord.review_report.model_route_resolution.candidates?.length"> · 候选 {{ selectedRecord.review_report.model_route_resolution.candidates.length }} 个</span></div>
    <div class="page-title-row"><div><p class="workspace-eyebrow">CASE GENERATION</p><h1>AI智能生成用例</h1><p class="workspace-lead">基于需求深度分析结果，五轮递进补充测试覆盖，再进行评审与自动化筛选。</p></div></div>
    <div v-if="notice" class="case-generation-notice" role="status">{{ notice }}</div><div v-if="skillExecution" class="case-generation-review case-generation-skill-status" role="status">本次自动调用：<b>{{ skillExecution.skill }}</b> · v{{ skillExecution.version }} · {{ skillStatusText[skillExecution.status] || skillExecution.status }}<span v-if="skillExecution.message"> · {{ skillExecution.message }}</span></div><div v-if="error" class="case-generation-error" role="alert">{{ error }} <button class="text-action" @click="load">重试</button></div>
    <div class="case-generation-toolbar"><label>项目<select v-model="selectedProject" @change="changeProject"><option v-for="item in projects" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><button class="secondary-action" @click="load">刷新</button></div>
    <div v-if="!loading && selectedAnalysisDocument" class="case-generation-source-status" role="status"><b>分析状态：{{ qualityLabel(selectedAnalysisDocument.latest_analysis.quality_status, selectedAnalysisDocument.latest_analysis) }}</b><span>模块 {{ selectedAnalysisDocument.latest_analysis.modules?.length || 0 }} · 功能点 {{ selectedAnalysisDocument.latest_analysis.functions?.length || 0 }} · 测试点 {{ selectedAnalysisDocument.latest_analysis.test_points?.length || 0 }}</span><small v-if="!isGenerationAllowed(selectedAnalysisDocument.latest_analysis)">{{ selectedAnalysisDocument.latest_analysis.quality_status === 'complete' ? '结构化分析已完成，但人工审核尚未完成。' : qualityReason(selectedAnalysisDocument) }}；请先到需求智能分析页面完成全部审核并确认。</small><small v-else>分析与人工审核均已完成，可进入正式用例生成。</small></div>
    <section v-if="loading" class="state-panel"><span class="loading-ring"></span><b>正在加载用例生成数据</b></section>
    <section v-else class="case-generation-layout"><aside class="case-generation-panel"><div class="case-generation-heading"><h2>用例生成记录</h2><span>{{ records.length }}</span></div><div v-if="!records.length" class="case-generation-empty">暂无用例生成记录，请先选择可用的需求分析结果。</div><div v-for="item in records" :key="item.id" class="case-generation-record" :class="{ active: item.id === selectedRecord?.id }" role="button" tabindex="0" @click="selectRecord(item)" @keydown.enter="selectRecord(item)"><div><b>用例集</b><small>来源：{{ item.document_title }} · {{ recordStatusText(item) }} · {{ item.total_cases }} 条</small></div><button class="case-generation-record-delete" :disabled="deletingRecordId === item.id || !recordCanDelete(item)" :title="recordCanDelete(item) ? '删除此记录' : '处理中不能删除'" @click.stop="deleteRecord(item)">{{ deletingRecordId === item.id ? '删除中…' : '删除' }}</button></div></aside>
      <main class="case-generation-panel">
        <div v-if="!selectedRecord" class="case-generation-empty">
          <h2>生成测试用例</h2>
          <p>选择已有需求分析结果后开始；待确认结果必须先在需求智能分析页面完成审核。</p>
          <select v-model="selectedDocument">
            <option value="">请选择需求分析结果</option>
            <option v-for="item in analyzedDocuments" :key="item.id" :value="item.id">
              {{ item.title }} v{{ item.version }} · {{ qualityLabel(item.latest_analysis.quality_status, item.latest_analysis) }}
            </option>
          </select>
          <label class="model-choice-label">用例生成模型<select v-model="generationModel" :disabled="optionsLoading || busy"><option value="">继承平台或功能默认</option><option v-for="model in generationOptions.models" :key="model.id" :value="String(model.id)">{{ model.name }} · {{ model.model_name }}（{{ model.model_type_label }}）</option></select></label>
           <small v-if="generationOptions.effective_model" class="model-choice-hint">当前生效：{{ generationOptions.effective_model.name }} · {{ generationOptions.effective_model.model_name }}</small>
           <div v-if="selectedAnalysisDocument" class="case-generation-approved-points"><b>已审核测试点（{{ approvedTestPoints.length }}）</b><small v-if="approvedTestPoints.length">只从已审核集合生成；可取消勾选不需要生成的测试点。</small><label v-for="item in approvedTestPoints" :key="item.id"><input type="checkbox" :value="String(item.id)" v-model="selectedApprovedTestPointIds"><span>{{ item.description || item.scenario || '未命名测试点' }} · {{ designMethodLabel(item) }}</span></label><p v-if="!approvedTestPoints.length" class="case-generation-hint">暂无已审核测试点，请先回到需求分析页勾选并标记。</p></div>
           <button class="primary-action" :disabled="busy || !canWrite || !selectedDocument || !isGenerationAllowed(selectedAnalysisDocument?.latest_analysis) || !selectedApprovedTestPointIds.length" @click="runGenerate">{{ busy ? '生成中…' : '生成用例' }}</button>
          <p v-if="!analyzedDocuments.length" class="case-generation-hint">当前项目没有可用的需求分析结果。</p>
        </div>
        <template v-else>
          <p v-if="reviewEditing" class="case-review-scope-count">当前筛选范围 {{ filteredReviewDraftCases.length }} 条用例<span v-if="reviewEditFunctionId !== 'all'"> · 当前功能点筛选已生效</span></p>
          <div class="case-generation-heading"><div><h2>用例集</h2><small>来源：{{ selectedRecord.document_title }} · 生成 {{ selectedRecord.rounds }} 轮 · {{ recordStatusLabel }} · 评审状态：{{ reviewStatusLabel }}</small></div><div class="case-generation-actions"><button class="secondary-action" :disabled="busy || recordProcessing || !canWrite || !isGenerationAllowed(selectedAnalysisDocument?.latest_analysis)" @click="runGenerate">{{ generateButtonLabel }}</button><button class="secondary-action" :disabled="busy || recordProcessing || !canWrite || !selectedRecord.cases?.length || reviewCompleted" @click="runReview">{{ reviewButtonLabel }}</button><button class="secondary-action" :disabled="busy || recordProcessing || !canWrite || !selectedRecord.cases?.length || selectionDone" @click="runSelect">{{ selectButtonLabel }}</button><button v-if="activeTaskRuntime && canWrite" class="secondary-action" :disabled="busy" @click="cancelActiveCaseTask">取消任务</button></div></div>
          <div v-if="recordProcessing" class="case-generation-notice" role="status">当前任务{{ taskStatusText[activeTaskRuntime?.status] || recordStatusLabel }}：{{ activeTaskRuntime?.current_step || '后台处理中' }} · 第 {{ activeTaskRuntime?.current_round || 0 }} / {{ activeTaskRuntime?.total_rounds || 5 }} 轮；后台每 3 秒查询一次处理状态。</div><div v-else-if="isEmptyGenerationShell(selectedRecord)" class="case-generation-error" role="status">本次没有生成任何用例，请点击“重新生成”。</div><div v-else-if="reviewSkipped || (!selectedRecord.cases?.length && selectedRecord.status === 'reviewing')" class="case-generation-notice" role="status">暂无用例可评审，自动评审已结束；请先重新生成用例。</div>
          <div class="case-generation-model-bar"><label>用例生成模型<select v-model="generationModel" :disabled="optionsLoading || busy"><option value="">继承平台或功能默认</option><option v-for="model in generationOptions.models" :key="model.id" :value="String(model.id)">{{ model.name }} · {{ model.model_name }}</option></select></label><label>用例评审模型<select v-model="reviewModel" :disabled="optionsLoading || busy"><option value="">继承平台或功能默认</option><option v-for="model in reviewOptions.models" :key="model.id" :value="String(model.id)">{{ model.name }} · {{ model.model_name }}</option></select></label></div>
          <div class="case-generation-summary"><span>总用例 {{ selectedRecord.total_cases }}</span><span>自动化 {{ selectedRecord.auto_cases }}</span><span>手工 {{ selectedRecord.manual_cases }}</span><span v-for="key in Object.keys(coverageMetricConfig)" :key="`coverage-${key}`" :title="coverageMetricLabel(key)">{{ coverageMetricLabel(key) }} {{ coverageMetricText(selectedRecord.coverage_report, key) }}<small v-if="coverageMetricCount(selectedRecord.coverage_report, key)">（{{ coverageMetricCount(selectedRecord.coverage_report, key) }}）</small></span></div>
          <div v-if="selectedRecord.coverage_report?.coverage_metrics" class="case-generation-review case-generation-coverage-breakdown" role="status"><b>覆盖口径</b><span v-for="key in Object.keys(coverageMetricConfig)" :key="`coverage-detail-${key}`">{{ coverageMetricLabel(key) }}：{{ coverageMetricText(selectedRecord.coverage_report, key) }}<small v-if="coverageMetric(selectedRecord.coverage_report, key)?.uncovered_ids?.length"> · 未覆盖 {{ coverageMetric(selectedRecord.coverage_report, key).uncovered_ids.length }} 项</small></span></div>
          <div v-if="selectedRecord.coverage_report?.round_trace?.length" class="case-generation-review"><b>五轮递进生成</b><ul><li v-for="(round, index) in selectedRecord.coverage_report.round_trace" :key="round.round">第 {{ round.round }} 轮：{{ roundStage(round.stage) }}，新增 {{ round.added ?? 0 }} 条，累计 {{ roundTotal(round, index) }} 条</li></ul><p v-if="selectedRecord.coverage_report.model_warning" class="case-generation-error">部分轮次未能调用模型，已按记录的策略处理：{{ selectedRecord.coverage_report.model_warning }}</p></div>
          <details v-if="selectedRecord.review_report?.analysis_method" class="case-generation-review case-generation-review-report"><summary class="case-review-summary"><span>用例评审报告</span><small>{{ reviewStatusLabel }} · 模型复核 · {{ selectedRecord.review_report.issue_count || 0 }} 条问题 · 点击展开</small></summary><header class="case-review-header"><div><h3 id="case-review-title">用例评审报告</h3><p>评审结论：{{ reviewStatusLabel }} · 评审方式：{{ selectedRecord.review_report.analysis_method === 'model_verified' ? '模型复核' : '确定性基线' }}<span v-if="selectedRecord.review_report.issue_count !== undefined"> · 共 {{ selectedRecord.review_report.issue_count }} 条问题</span></p></div><div class="case-review-counts"><span class="case-review-count case-review-count--high">高 {{ reviewIssueSummary.high }}</span><span class="case-review-count case-review-count--medium">中 {{ reviewIssueSummary.medium }}</span><span class="case-review-count case-review-count--low">低 {{ reviewIssueSummary.low }}</span></div></header><p v-if="selectedRecord.review_report.model_warning" class="case-generation-error">模型评审未完成：{{ selectedRecord.review_report.model_warning }}</p><div v-if="selectedRecord.review_report.issues?.length" class="case-review-issues"><article v-for="(issue, index) in selectedRecord.review_report.issues" :key="issue.id || `review-issue-${index}`" class="case-review-issue" :class="`case-review-issue--${issue.severity || 'medium'}`"><header class="case-review-issue-header"><div><span class="case-review-severity">{{ issueSeverityLabel(issue) }}</span><strong>{{ issue.case_id || `评审问题 ${index + 1}` }}</strong><span class="case-review-dimension">{{ issueDimensionLabel(issue) }}</span></div><small>问题 {{ index + 1 }} / {{ selectedRecord.review_report.issues.length }}</small></header><div class="case-review-field"><h4>问题描述</h4><p>{{ issue.description || '评审结果未提供问题描述。' }}</p></div><div class="case-review-field"><h4>修改建议</h4><p>{{ issue.suggestion || '请结合需求原文和测试步骤进行人工复核。' }}</p></div><p v-if="issue.evidence_ids?.length" class="case-review-evidence">关联证据：{{ issue.evidence_ids.join('、') }}</p></article></div><div v-else class="case-review-empty">本轮评审未发现问题。</div></details>
          <div v-if="selectedRecord.cases?.length && selectedRecord.review_report?.analysis_method" class="case-review-editor-panel"><div class="case-review-editor-heading"><div><h3>人工修订评审用例</h3><p>默认先处理大模型评审报告关联的用例；也可切换范围和功能点，继续人工审核其他已生成用例。</p></div><button v-if="!reviewEditing" class="primary-action case-review-edit-primary" :disabled="busy || reviewSaving || recordProcessing || !canWrite" @click="beginReviewEditing">人工修订</button></div><template v-if="reviewEditing"><div class="case-review-editor-toolbar"><label>评审范围<select v-model="reviewEditScope"><option value="llm_issues">LLM评审问题用例</option><option value="pending_review">待评审用例</option><option value="all">全部用例</option><option value="final">最终用例</option><option value="generated">已生成用例</option></select></label><label>功能点<select v-model="reviewEditFunctionId"><option value="all">全部功能点</option><option v-for="item in reviewEditFunctionOptions" :key="item.id" :value="item.id">{{ item.name || item.description || item.id }}</option></select></label><label>选择用例<select v-model="activeReviewCaseKey"><option v-for="item in filteredReviewDraftCases" :key="item.id" :value="item.id">{{ item.id }} · {{ item.title }}</option><option v-for="item in newReviewCases" :key="item._key" :value="'new:' + item._key">新增用例 · {{ item.title || '未命名' }}</option></select></label><button class="secondary-action" @click="addReviewCaseDraft">新增补充用例</button></div><p v-if="!filteredReviewDraftCases.length && !newReviewCases.length" class="case-review-editor-empty">当前筛选范围没有可人工修订的用例，可切换评审范围或新增补充用例。</p><div v-if="activeReviewCase" class="case-review-editor-form"><div v-if="activeReviewIssues.length" class="case-review-source-issues"><h4>LLM评审依据</h4><article v-for="(issue, index) in activeReviewIssues" :key="issue.id || index"><b>{{ issueSeverityLabel(issue) }} · {{ issueDimensionLabel(issue) }}</b><p>{{ issue.description }}</p><small>修改建议：{{ issue.suggestion }}</small></article></div><label>用例标题<input v-model="activeReviewCase.title" maxlength="300"></label><label>测试步骤<textarea v-model="activeReviewCase.steps_text" rows="5" placeholder="每行一个执行步骤"></textarea></label><label>预期结果<textarea v-model="activeReviewCase.expected_result" rows="4"></textarea></label><div class="case-review-editor-inline"><label>关联功能点<select v-model="activeReviewCase.source_function_id"><option value="">未关联功能点</option><option v-for="item in selectedAnalysisDocument?.latest_analysis?.functions || []" :key="item.id" :value="item.id">{{ item.name || item.description || item.id }}</option></select></label><label>优先级<select v-model="activeReviewCase.priority"><option>P0</option><option>P1</option><option>P2</option></select></label><label>测试设计方法<select v-model="activeReviewCase.test_design_method"><option value="positive_flow">正向流程</option><option value="equivalence_class">等价类</option><option value="boundary_value">边界值</option><option value="error_guessing">错误猜测法</option><option value="cause_effect_graph">因果图</option><option value="state_transition">状态转换</option><option value="security">安全</option><option value="performance">性能</option><option value="linkage">联动</option><option value="regression_compatibility">回归兼容</option></select></label><label class="case-review-editor-checkbox"><input type="checkbox" v-model="activeReviewCase.automatable"> 建议自动化</label></div><button v-if="activeReviewCase.id && !isManualConfirmed(activeReviewCase)" class="secondary-action" @click="confirmActiveCase">确认当前用例已人工审核</button><span v-else-if="activeReviewCase.id" class="case-review-confirmed-label">当前用例已加入人工确认</span><button v-if="activeReviewCaseKey.startsWith('new:')" class="text-action" @click="removeReviewCaseDraft(activeReviewCase._key)">取消新增此用例</button></div><div class="case-review-editor-actions"><button class="primary-action" :disabled="reviewSaving" @click="saveManualReviewCases">确认保存人工评审结果</button><button class="secondary-action" :disabled="reviewSaving" @click="cancelReviewEditing">取消修改</button></div></template><div v-if="manualRevision?.status === 'saved_pending_review'" class="case-generation-notice">人工修订已保存 {{ manualRevision.revision_number }} 次，当前用例等待重新评审。</div></div>
          <div class="case-generation-cases-heading"><div><h3>测试用例</h3><p>请以此处用例作为执行清单，评审报告可展开用于定位和修正问题。</p></div><strong>{{ selectedRecord.cases?.length || 0 }} 条</strong></div><div class="case-filter-bar"><button v-for="filter in [{ key: 'all', label: '全部' }, { key: 'pending_review', label: '待评审' }, { key: 'auto_passed', label: '无需人工评审' }, { key: 'final', label: '最终用例' }, { key: 'generated', label: '已生成' }]" :key="filter.key" class="case-filter-button" :class="{ active: caseFilter === filter.key }" @click="caseFilter = filter.key">{{ filter.label }}（{{ filter.key === 'final' ? caseCounts.final : caseCounts[filter.key] }}）</button></div><p v-if="manualRevision?.status === 'saved_pending_review'" class="case-generation-notice">人工修订已加入当前用例表格，请点击上方“评审”重新确认。</p><p v-else-if="selectedRecord.review_report?.approved === false && !reviewSkipped" class="case-generation-error">评审未通过，请根据上方评审报告的问题修正用例后，点击“重新生成”或使用上方“人工修订”。</p><div v-if="!selectedRecord.cases?.length" class="case-generation-empty">当前记录没有可展示的用例。</div><template v-else><table class="case-generation-table"><thead><tr><th>功能点</th><th>编号</th><th>标题</th><th>状态</th><th>类型</th><th>测试设计方法</th><th>优先级</th><th>自动化</th><th>预期结果</th></tr></thead><tbody><tr v-for="item in shownCases" :key="item.id"><td>{{ caseFunctionLabel(item) }}</td><td>{{ item.id }}</td><td>{{ item.title }}<small v-if="item.manual_revision_label" class="case-manual-label">（{{ item.manual_revision_label }}）</small></td><td><span class="case-status-label" :class="`case-status-label--${caseReviewStatus(item)}`">{{ caseStatusLabel(item) }}</span></td><td>{{ item.type }}</td><td>{{ designMethodLabel(item) }}</td><td>{{ item.priority }}</td><td>{{ item.automatable ? '建议自动化' : '建议手工' }}</td><td>{{ item.expected_result }}</td></tr></tbody></table><button v-if="hasMoreCases" class="secondary-action case-generation-more" @click="visibleCases += 100">加载更多（已显示 {{ shownCases.length }} / {{ filteredCases.length }}）</button></template>
        </template>
      </main>
    </section>
    <div v-if="!selectedRecord && blockedDocuments.length" class="case-generation-hint">存在尚未完成人工审核的需求分析结果，请先在需求分析页完成全部审核并确认后再生成用例。</div>
    <div v-if="hasStructuredGeneration" class="case-generation-review" role="status">长内容已按分段执行并合并结果。</div><div v-if="selectedRecord?.coverage_report?.generation_status === 'partial'" class="case-generation-error" role="alert">用例生成部分完成，已保留已有结果；请重新执行以恢复失败分段，当前结果不能视为完整模型验证。</div><div v-if="selectedRecord?.review_report?.analysis_method === 'model_partial'" class="case-generation-error" role="alert">用例评审部分完成，已保留已有评审问题；请重新评审恢复失败分段。</div>
  </div></WorkspaceShell>
</template>
