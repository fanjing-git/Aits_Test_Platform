<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'
import { listProjects } from '../api/projects'
import { generateCaseRecord } from '../api/caseGeneration'
import { analyzeRequirementDocument, analyzeRequirementScreenshot, cancelRequirementAnalysis, clearRequirementAnalysis, confirmRequirementAnalysis, createRequirementDocument, deleteRequirementDocument, getRequirementAnalysisProgress, identifyRequirementLinkages, listRequirementDocuments, listRequirementModelOptions, parseRequirementDocument, reviewRequirementTestPoints, retryRequirementAnalysisRound } from '../api/requirements'

const projects = ref([]); const documents = ref([]); const selectedProject = ref(''); const selectedDocument = ref(null)
const loading = ref(true); const busy = ref(false); const error = ref(''); const notice = ref(''); const formError = ref(''); const showForm = ref(false)
const file = ref(null); const form = reactive({ title: '', version: '1.0', source_type: 'manual', source_url: '', content_text: '' })
const screenshotReport = ref(null)
const skillExecution = ref(null)
const lastAction = ref(null); const failureMeta = ref(null)
const busyLabel = ref('正在处理，请稍候'); const busyOperation = ref(''); const busyElapsed = ref(0); let busyTimer = null
const router = useRouter()
const modelOptions = ref(null); const modelOptionsLoading = ref(false); const modelChoice = ref('')
const analysisProgress = ref(null); const analysisProgressError = ref(''); const roundRetryBusy = ref(false); const retryingRound = ref(null)
const activeTask = ref(null)
const testPointPageSize = 80; const visibleTestPointCount = ref(testPointPageSize)
const MAX_REQUIREMENT_FILE_BYTES = 10 * 1024 * 1024
const visibleTestPoints = computed(() => (selectedDocument.value?.latest_analysis?.test_points || []).slice(0, visibleTestPointCount.value))
const reviewedTestPointIds = ref([]); const selectedTestPointIds = ref([]); const reviewedEvidenceIds = ref([]); const reviewedAnalysisItemIds = ref([]); const reviewedConflictIds = ref([])
const testTypeLabels = { positive: '正向', negative: '异常', boundary: '边界', security: '安全', linkage: '联动', performance: '性能' }
const hasAnalysisRecords = computed(() => Boolean(selectedDocument.value?.latest_analysis || Object.keys(selectedDocument.value?.visual_analysis_report || {}).length))
const qualityBanner = computed(() => {
  const report = selectedDocument.value?.latest_analysis?.coverage_report || {}
  const qualityStatus = report.quality_status || selectedDocument.value?.latest_analysis?.quality_status
  if (!qualityStatus) return null
  const coverage = report.evidence_coverage || {}
  const comparison = report.analysis_comparison
  const drops = Object.entries(comparison?.delta || {}).filter(([, value]) => value < 0).map(([key, value]) => `${key} ${value}`)
  const coverageDetail = coverage.total_evidence ? `证据覆盖 ${coverage.covered_evidence || 0} / ${coverage.total_evidence}，未引用分析项 ${coverage.uncited_item_count || 0}。` : ''
  if (qualityStatus === 'complete') {
    const manualComplete = Boolean(selectedDocument.value?.latest_analysis?.manual_review_complete ?? (report.manual_confirmation?.confirmed === true))
    return { className: manualComplete ? 'requirement-source-meta' : 'requirement-notice', title: manualComplete ? '分析与人工审核均已完成' : '分析完成，待人工审核', detail: `${manualComplete ? '结果可进入正式用例生成。' : '结构化分析已完成，但未完成人工审核确认，暂不能进入正式用例生成。'} 证据覆盖 ${coverage.covered_evidence || 0} / ${coverage.total_evidence || 0}。` }
  }
  return { className: 'requirement-error', title: qualityStatus === 'partial' ? '分析部分完成' : '分析结果待复核', detail: `${report.quality_reason || '当前结果不能直接视为完整模型验证。'}${coverageDetail ? ` ${coverageDetail}` : ''}${drops.length ? ` 数量变化：${drops.join('、')}。` : ''}` }
})
const analysisReview = computed(() => {
  const analysis = selectedDocument.value?.latest_analysis
  if (!analysis || !['needs_review', 'complete'].includes(analysis.quality_status)) return null
  const report = analysis.coverage_report || {}
  const coverage = report.evidence_coverage || {}
  const evidenceById = new Map((selectedDocument.value.parse_evidence || []).map(item => [String(item.id), item]))
  const uncoveredEvidence = (coverage.uncovered_evidence_ids || []).map(id => evidenceById.get(String(id)) || { id })
  const groups = [['模块', 'modules'], ['功能点', 'functions'], ['联合场景', 'linkages'], ['测试点', 'test_points']]
  const uncitedItems = groups.flatMap(([group, key]) => (analysis[key] || []).filter(item => !Array.isArray(item.evidence_ids) || !item.evidence_ids.length).map(item => ({ id: item.id, group, label: item.name || item.description || item.scenario || item.relationship || item.id })))
  const functionById = new Map((analysis.functions || []).map(item => [String(item.id), item]))
  const moduleById = new Map((analysis.modules || []).map(item => [String(item.id), item]))
  const linkageById = new Map((analysis.linkages || []).map(item => [String(item.id), item]))
  const reviewPoints = (analysis.test_points || []).map(item => {
    const functionItem = functionById.get(String(item.function_id || item.source_function_id))
    const moduleItem = moduleById.get(String(functionItem?.module_id || item.module_id))
    const linkageItem = linkageById.get(String(item.scenario_id || item.linkage_id))
    const sourceFunction = linkageItem ? functionById.get(String(linkageItem.from || linkageItem.source_function_id)) : null
    const targetFunction = linkageItem ? functionById.get(String(linkageItem.to || linkageItem.target_function_id)) : null
    const sourceModule = sourceFunction ? moduleById.get(String(sourceFunction.module_id)) : null
    const targetModule = targetFunction ? moduleById.get(String(targetFunction.module_id)) : null
    const linkageModules = [...new Set([sourceModule?.name, targetModule?.name].filter(Boolean))]
    const evidenceIds = Array.isArray(item.evidence_ids) ? item.evidence_ids : []
    const evidenceLabels = evidenceIds.map(id => evidenceById.get(String(id))?.text || '原文证据片段')
    const normalizedType = String(item.type || '').trim().toLowerCase()
    return { ...item, functionLabel: linkageItem ? `联合场景：${sourceFunction?.name || '未知功能点'} → ${targetFunction?.name || '未知功能点'}` : (functionItem?.name || functionItem?.description || '未关联功能点'), moduleLabel: linkageItem ? `联合模块：${linkageModules.join(' ↔ ') || '待补充模块'}` : (moduleItem?.name || '未关联模块'), evidenceLabels, typeLabel: testTypeLabels[normalizedType] || '未标注' }
  })
  const validFunctionIds = new Set((analysis.functions || []).filter(item => moduleById.has(String(item.module_id))).map(item => String(item.id)))
  const validLinkageIds = new Set((analysis.linkages || []).filter(item => validFunctionIds.has(String(item.from || item.source_function_id)) && validFunctionIds.has(String(item.to || item.target_function_id))).map(item => String(item.id)))
  const mappingGapGroups = [
    {
      label: '功能模块缺少名称',
      items: (analysis.modules || []).filter(item => !String(item.name || '').trim()).map(item => ({ id: item.id, title: '当前模块未提供名称', detail: '模型只返回了模块编号，无法在审核表中显示可读模块' })),
    },
    {
      label: '功能点未关联模块',
      items: (analysis.functions || []).filter(item => !moduleById.has(String(item.module_id))).map(item => ({ id: item.id, title: item.name || item.description || '未命名功能点', detail: '当前没有关联到功能模块' })),
    },
    {
      label: '功能点缺少名称',
      items: (analysis.functions || []).filter(item => !String(item.name || '').trim()).map(item => ({ id: item.id, title: '当前功能点未提供名称', detail: '模型只返回了功能点编号和证据，无法在审核表中显示可读功能点' })),
    },
    {
      label: '联合场景未关联有效功能点',
      items: (analysis.linkages || []).filter(item => !validLinkageIds.has(String(item.id))).map(item => {
        const source = functionById.get(String(item.from || item.source_function_id))
        const target = functionById.get(String(item.to || item.target_function_id))
        return { id: item.id, title: item.description || item.relationship || '未命名联合场景', detail: `${source?.name || '未知功能点'} → ${target?.name || '未知功能点'}` }
      }),
    },
    {
      label: '测试点未关联功能点或联合场景',
      items: (analysis.test_points || []).filter(item => !validFunctionIds.has(String(item.function_id || item.source_function_id)) && !validLinkageIds.has(String(item.scenario_id || item.linkage_id))).map(item => ({ id: item.id, title: item.description || item.scenario || '未命名测试点', detail: `测试类型：${item.type || '未分类'}` })),
    },
    {
      label: '测试点缺少描述',
      items: (analysis.test_points || []).filter(item => !String(item.description || '').trim()).map(item => ({ id: item.id, title: '当前测试点未提供描述', detail: '模型只返回了测试点编号和证据，无法进行人工审核' })),
    },
    {
      label: '测试点未标注测试类型',
      items: (analysis.test_points || []).filter(item => !String(item.type || '').trim()).map(item => ({ id: item.id, title: item.description || item.scenario || '未命名测试点', detail: '当前没有标注正向、异常、边界、安全、联动或性能分类' })),
    },
    {
      label: '测试点类型无法识别',
      items: (analysis.test_points || []).filter(item => { const type = String(item.type || '').trim().toLowerCase(); return type && !testTypeLabels[type] }).map(item => ({ id: item.id, title: item.description || item.scenario || '未命名测试点', detail: `当前分类：${item.type}` })),
    },
  ].filter(group => group.items.length)
  const drops = Object.entries(report.analysis_comparison?.delta || {}).filter(([, value]) => value < 0).map(([key, value]) => `${key} ${value}`)
  const conflicts = (Array.isArray(report.conflicts) ? report.conflicts : []).map((item, index) => {
    const reviewId = String(item.id || `legacy-conflict-${index + 1}`)
    const fieldSummary = (Array.isArray(item.fields) ? item.fields : []).map(field => `${field.field}: ${JSON.stringify(field.existing_value)} → ${JSON.stringify(field.incoming_value)}`).join('；')
    return { ...item, reviewId, fieldSummary: fieldSummary || '同一业务对象的语义或标识发生变化' }
  })
  return { uncoveredEvidence, uncitedItems, reviewPoints, mappingGapGroups, drops, conflicts, totalEvidence: coverage.total_evidence || 0, coveredEvidence: coverage.covered_evidence || 0 }
})
const reviewReady = computed(() => {
  if (!analysisReview.value) return false
  const includesAll = (selected, expected) => expected.every(id => selected.includes(String(id)))
  return !analysisReview.value.mappingGapGroups.length
    && includesAll(reviewedTestPointIds.value, analysisReview.value.reviewPoints.map(item => item.id))
    && includesAll(reviewedEvidenceIds.value, analysisReview.value.uncoveredEvidence.map(item => item.id))
    && includesAll(reviewedAnalysisItemIds.value, analysisReview.value.uncitedItems.map(item => item.id))
    && includesAll(reviewedConflictIds.value, analysisReview.value.conflicts.map(item => item.reviewId))
})
const approvedReviewPoints = computed(() => {
  const approved = new Set(reviewedTestPointIds.value.map(String))
  return (analysisReview.value?.reviewPoints || []).filter(item => approved.has(String(item.id)))
})
const pendingReviewPoints = computed(() => {
  const approved = new Set(reviewedTestPointIds.value.map(String))
  return (analysisReview.value?.reviewPoints || []).filter(item => !approved.has(String(item.id)))
})
const allReviewPointsSelected = computed(() => Boolean(pendingReviewPoints.value.length) && pendingReviewPoints.value.every(item => selectedTestPointIds.value.includes(String(item.id))))
const analysisConfirmed = computed(() => Boolean(selectedDocument.value?.latest_analysis?.manual_review_complete ?? (selectedDocument.value?.latest_analysis?.quality_status === 'complete' && selectedDocument.value?.latest_analysis?.coverage_report?.manual_confirmation?.confirmed === true)))
const modelVerificationLabel = computed(() => {
  const report = selectedDocument.value?.latest_analysis?.coverage_report || {}
  const qualityStatus = report.quality_status || selectedDocument.value?.latest_analysis?.quality_status
  if (qualityStatus !== 'complete') return '调用已验证，结果待复核'
  return analysisConfirmed.value ? '调用、完整性与人工审核均通过' : '调用与完整性通过，待人工审核'
})
const confirmButtonLabel = computed(() => busyOperation.value === 'case_generation' ? '审核并生成中…' : '确认审核并生成测试用例')
const busyElapsedLabel = computed(() => {
  const minutes = Math.floor(busyElapsed.value / 60)
  const seconds = busyElapsed.value % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
})
const busyHint = computed(() => busyElapsed.value >= 30
  ? '仍在等待模型返回结构化结果，长需求会按分段串行处理，请不要重复点击。'
  : '请求已提交，正在执行结构化分析，请不要重复点击。')

function startBusy(label) { busyLabel.value = label; busyElapsed.value = 0; clearInterval(busyTimer); busyTimer = window.setInterval(() => { busyElapsed.value += 1 }, 1000) }
function stopBusy() { clearInterval(busyTimer); busyTimer = null }
const canWrite = computed(() => ['admin', 'platform_admin', 'owner', 'manager'].includes(selectedProject.value ? projects.value.find(item => item.id === selectedProject.value)?.current_role : ''))
const skillStatusText = { completed: '已完成', failed: '失败', needs_input: '等待补充' }
const roundStatusText = { pending: '待执行', running: '执行中', completed: '已完成', partial: '部分完成', failed: '失败', blocked: '未执行', not_configured: '未配置模型' }
const taskStatusText = { pending: '排队中', running: '执行中', cancel_requested: '取消中', completed: '已完成', failed: '失败', cancelled: '已取消', timed_out: '已超时' }
const taskIsActive = computed(() => ['pending', 'running', 'cancel_requested'].includes(activeTask.value?.status))

function explain(err, fallback) { const data = err.response?.data; if (typeof data?.detail === 'string') return data.detail; if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') return '结构化分析等待时间过长，后端可能仍在处理；请刷新页面查看是否已保存部分结果，或稍后重试。'; const first = data && Object.values(data)[0]; return Array.isArray(first) ? first[0] : (typeof first === 'string' ? first : fallback) }
async function loadProjects() { try { projects.value = await listProjects(); if (!selectedProject.value && projects.value.length) selectedProject.value = projects.value[0].id } catch (err) { error.value = explain(err, '项目加载失败，请确认服务状态后重试。') } }
async function loadRoundProgress() { analysisProgressError.value = ''; if (!selectedDocument.value) { analysisProgress.value = null; return }; try { analysisProgress.value = await getRequirementAnalysisProgress(selectedDocument.value.id) } catch (err) { analysisProgress.value = null; analysisProgressError.value = explain(err, '五轮进度加载失败，请刷新重试。') } }
async function loadDocuments() { if (!selectedProject.value) { documents.value = []; selectedDocument.value = null; screenshotReport.value = null; analysisProgress.value = null; loading.value = false; return }; loading.value = true; error.value = ''; try { documents.value = await listRequirementDocuments(selectedProject.value); selectedDocument.value = documents.value.find(item => item.id === selectedDocument.value?.id) || documents.value[0] || null; screenshotReport.value = selectedDocument.value?.visual_analysis_report || null; await loadRoundProgress() } catch (err) { error.value = explain(err, '需求文档加载失败，请重试。') } finally { loading.value = false } }
async function loadModelOptions() { if (!selectedDocument.value) { modelOptions.value = null; modelChoice.value = ''; return }; modelOptionsLoading.value = true; try { modelOptions.value = await listRequirementModelOptions(selectedDocument.value.id); modelChoice.value = '' } catch (err) { modelOptions.value = { models: [], route_error: explain(err, '模型选项加载失败，请重试。') } } finally { modelOptionsLoading.value = false } }
async function refresh() { await loadProjects(); await loadDocuments() }
async function waitForRequirementTask(documentId, response) {
  let task = response?.task_runtime || null
  if (!taskIsActive.value && !['pending', 'running', 'cancel_requested'].includes(task?.status)) return response
  activeTask.value = task
  for (let attempt = 0; attempt < 1200; attempt += 1) {
    await new Promise(resolve => window.setTimeout(resolve, 1500))
    const progress = await getRequirementAnalysisProgress(documentId)
    analysisProgress.value = progress
    task = progress?.task_runtime || task
    activeTask.value = task
    if (!['pending', 'running', 'cancel_requested'].includes(task?.status)) {
      await loadDocuments()
      if (task?.status === 'cancelled') return { ...response, task_runtime: task, __cancelled: true }
      const terminalError = ['failed', 'timed_out'].includes(task?.status)
      if (terminalError) throw new Error(`后台任务${taskStatusText[task.status] || '未完成'}：${task.error_code || '请查看任务详情后重试。'}`)
      return documents.value.find(item => item.id === documentId) || response
    }
  }
  throw new Error('后台任务等待超过30分钟，请刷新页面查看最终状态。')
}
async function cancelActiveRequirementTask() {
  if (!selectedDocument.value || !taskIsActive.value || !canWrite.value) return
  try {
    const result = await cancelRequirementAnalysis(selectedDocument.value.id)
    activeTask.value = result?.task_runtime || activeTask.value
    notice.value = '已提交取消请求，后台会在当前安全检查点停止。'
  } catch (err) { error.value = explain(err, '取消后台任务失败，请稍后重试。') }
}
function openCreate() { if (!projects.value.length || !selectedProject.value) { router.push({ name: 'project-agents' }); return }; if (!canWrite.value) { error.value = '当前项目角色没有上传需求文档权限，请联系项目所有者或管理员。'; return }; Object.assign(form, { title: '', version: '1.0', source_type: 'manual', source_url: '', content_text: '' }); file.value = null; formError.value = ''; showForm.value = true }
function onFile(event) { const selected = event.target.files?.[0] || null; if (selected && selected.size > MAX_REQUIREMENT_FILE_BYTES) { file.value = null; event.target.value = ''; formError.value = '文件超过10MB限制，请压缩文件或拆分后重新上传。'; return }; file.value = selected; formError.value = '' }
async function saveDocument() { formError.value = ''; if (!selectedProject.value || !form.title.trim()) { formError.value = '请选择项目并填写文档标题。'; return }; if (form.source_type === 'manual' && !form.content_text.trim()) { formError.value = '手工录入内容不能为空。'; return }; if (form.source_type === 'file' && !file.value) { formError.value = '请选择需求文件。'; return }; if (form.source_type === 'screenshot' && !file.value && !form.content_text.trim()) { formError.value = '截图来源请上传图片或填写 OCR 正文。'; return }; if (form.source_type === 'online_link' && !form.source_url.trim()) { formError.value = '在线来源必须填写链接。'; return }; busy.value = true; try { const payload = new FormData(); payload.append('project', selectedProject.value); payload.append('title', form.title); payload.append('version', form.version); payload.append('source_type', form.source_type); if (form.source_url) payload.append('source_url', form.source_url); if (form.content_text) payload.append('content_text', form.content_text); if (file.value) payload.append('file', file.value); const created = await createRequirementDocument(payload); showForm.value = false; notice.value = '需求文档已创建，请继续解析和分析。'; await loadDocuments(); selectedDocument.value = created } catch (err) { formError.value = explain(err, '保存失败，请检查文档内容后重试。') } finally { busy.value = false } }
async function action(fn, success) {
  if (!selectedDocument.value) return
  lastAction.value = { fn, success }; failureMeta.value = null; busy.value = true; error.value = ''
  try {
    const needsModel = fn === analyzeRequirementDocument || fn === analyzeRequirementScreenshot
    const payload = needsModel && modelChoice.value ? { model_config_id: Number(modelChoice.value) } : {}
    const documentId = selectedDocument.value.id
    const result = await fn(documentId, payload)
    skillExecution.value = result?.skill_execution || null
    if (fn === analyzeRequirementScreenshot) screenshotReport.value = result
    const completed = fn === analyzeRequirementDocument || fn === retryRequirementAnalysisRound ? await waitForRequirementTask(documentId, result) : result
    notice.value = completed?.__cancelled ? '任务已取消，已在安全检查点停止。' : (fn === identifyRequirementLinkages && !result?.linkages?.length ? '联合识别已完成，当前需求未发现跨模块联动场景。' : success)
    lastAction.value = null; await loadDocuments(); selectedDocument.value = documents.value.find(item => item.id === documentId) || completed
  } catch (err) {
    const data = err.response?.data || {}; failureMeta.value = { code: data.code || '', status: data.status || 'failed', retryable: data.retryable !== false }; error.value = explain(err, '操作失败，请重试。')
  } finally { activeTask.value = null; busy.value = false }
}
async function retryRound(round) { if (!selectedDocument.value || !canWrite.value || roundRetryBusy.value || busy.value) return; roundRetryBusy.value = true; retryingRound.value = Number(round.round); busyLabel.value = '正在重试第 ' + round.round + ' 轮'; busy.value = true; error.value = ''; notice.value = '已提交第 ' + round.round + ' 轮重试，正在等待模型返回结构化结果。'; try { const payload = { resume_round: Number(round.round) }; if (modelChoice.value) payload.model_config_id = Number(modelChoice.value); const documentId = selectedDocument.value.id; const result = await retryRequirementAnalysisRound(documentId, payload); skillExecution.value = result?.skill_execution || null; await waitForRequirementTask(documentId, result); notice.value = '第 ' + round.round + ' 轮重试已完成，分析进度已刷新。'; await loadDocuments(); selectedDocument.value = documents.value.find(item => item.id === documentId) || result } catch (err) { const data = err.response?.data || {}; failureMeta.value = { code: data.code || '', status: data.status || 'failed', retryable: data.retryable !== false }; error.value = explain(err, '轮次重试失败，请检查模型配置后重试。') } finally { activeTask.value = null; roundRetryBusy.value = false; retryingRound.value = null; busy.value = false } }
async function persistReviewSelection(ids) { const result = await reviewRequirementTestPoints(selectedDocument.value.id, { reviewed_test_point_ids: [...new Set([...reviewedTestPointIds.value, ...ids])] }); selectedDocument.value = result; reviewedTestPointIds.value = result.latest_analysis?.coverage_report?.manual_confirmation?.reviewed_test_point_ids?.map(String) || []; selectedTestPointIds.value = []; await loadDocuments(); selectedDocument.value = documents.value.find(item => item.id === selectedDocument.value?.id) || result; return result }
async function confirmAnalysis() {
  if (!selectedDocument.value || !analysisReview.value || !canWrite.value || busy.value || (!selectedTestPointIds.value.length && !reviewedTestPointIds.value.length)) return
  const documentId = selectedDocument.value.id
  busyOperation.value = 'case_generation'; busyLabel.value = '正在为已审核测试点生成测试用例'; busy.value = true; error.value = ''; failureMeta.value = null
  try {
    if (selectedTestPointIds.value.length) await persistReviewSelection(selectedTestPointIds.value)
    const reviewedIds = [...new Set(reviewedTestPointIds.value.map(String))]
    if (!reviewReady.value) {
      notice.value = `已审核 ${reviewedIds.length} 条测试点，但完整人工审核尚未完成；暂不生成用例，请继续完成审核清单。`
      return
    }
    await confirmRequirementAnalysis(documentId, { reviewed_test_point_ids: reviewedIds, reviewed_evidence_ids: reviewedEvidenceIds.value, reviewed_analysis_item_ids: reviewedAnalysisItemIds.value, reviewed_conflict_ids: reviewedConflictIds.value })
    await loadDocuments()
    selectedDocument.value = documents.value.find(item => item.id === documentId) || selectedDocument.value
    busyLabel.value = '正在为已审核测试点生成测试用例'
    notice.value = `已审核 ${reviewedIds.length} 条测试点，正在生成对应测试用例，请勿重复点击。`
    const generated = await generateCaseRecord(documentId, modelChoice.value, reviewedIds)
    if (!generated?.id) throw new Error('用例生成接口未返回生成记录编号，请到用例生成页面刷新查看。')
    router.push({ name: 'case-generation', query: { document: documentId, record: generated.id } })
  } catch (err) {
    error.value = explain(err, '审核已保存，但用例生成失败，请到用例生成页重试。')
  } finally { busy.value = false; busyOperation.value = '' }
}
async function markSelectedTestPointsReviewed() { if (!selectedDocument.value || !selectedTestPointIds.value.length || !canWrite.value || busy.value) return; busy.value = true; error.value = ''; try { await persistReviewSelection(selectedTestPointIds.value); notice.value = `已将 ${reviewedTestPointIds.value.length} 条测试点放入“已审核测试点”。` } catch (err) { error.value = explain(err, '保存已审核测试点失败，请重试。') } finally { busy.value = false } }
function selectAllReviewPoints() { selectedTestPointIds.value = pendingReviewPoints.value.map(item => String(item.id)) }
function clearReviewPointSelection() { selectedTestPointIds.value = [] }
function syncReviewState(document) { const confirmation = document?.latest_analysis?.coverage_report?.manual_confirmation || {}; reviewedTestPointIds.value = (confirmation.reviewed_test_point_ids || []).map(String); reviewedConflictIds.value = (confirmation.reviewed_conflict_ids || []).map(String); selectedTestPointIds.value = [] }
async function retryLastAction() { if (lastAction.value && !busy.value) await action(lastAction.value.fn, lastAction.value.success) }
async function removeDocument() { if (!selectedDocument.value || !window.confirm('确定删除当前需求文档吗？')) return; busy.value = true; try { await deleteRequirementDocument(selectedDocument.value.id); selectedDocument.value = null; notice.value = '需求文档已删除。'; await loadDocuments() } catch (err) { error.value = explain(err, '删除失败，请重试。') } finally { busy.value = false } }
async function clearAnalysisRecords() { if (!selectedDocument.value || !window.confirm('确定清除当前需求的分析记录吗？需求原文、文件和解析证据会保留，已有用例生成记录不会删除。最近一次分析摘要会保留用于下一次结果稳定性比较。')) return; busy.value = true; error.value = ''; notice.value = ''; try { const result = await clearRequirementAnalysis(selectedDocument.value.id); screenshotReport.value = null; skillExecution.value = null; notice.value = `分析记录已清除（${result.cleared_analysis_count || 0} 条），需求原文和解析证据已保留${result.analysis_baseline_preserved ? '，最近一次分析基线也已保留用于复核' : ''}。`; await loadDocuments() } catch (err) { error.value = explain(err, '清除分析记录失败，请重试。') } finally { busy.value = false } }
function loadMoreTestPoints() { visibleTestPointCount.value += testPointPageSize }
watch(() => selectedDocument.value?.id, () => { visibleTestPointCount.value = testPointPageSize; syncReviewState(selectedDocument.value); reviewedEvidenceIds.value = []; reviewedAnalysisItemIds.value = []; screenshotReport.value = selectedDocument.value?.visual_analysis_report || null; loadModelOptions(); loadRoundProgress() })
watch(busy, (value) => {
  if (value) {
    const fn = lastAction.value?.fn
    const label = busyOperation.value === 'case_generation' ? '正在为已审核测试点生成测试用例' : (roundRetryBusy.value ? '正在重试第 ' + retryingRound.value + ' 轮' : (fn === analyzeRequirementDocument ? '正在执行需求深度分析' : fn === analyzeRequirementScreenshot ? '正在执行截图视觉分析' : '正在处理，请稍候'))
    startBusy(label)
  } else stopBusy()
})
onBeforeUnmount(stopBusy)
onMounted(refresh)
</script>

<template>
  <WorkspaceShell active="requirements"><div class="workspace-content requirement-page">
    <div v-if="busy" class="requirement-progress" role="status" aria-live="polite" aria-busy="true"><span class="loading-ring"></span><div><b>{{ busyLabel }}</b><span>已等待 {{ busyElapsedLabel }}</span><small v-if="activeTask">{{ taskStatusText[activeTask.status] || activeTask.status }} · {{ activeTask.current_step || '正在处理' }} · 第 {{ activeTask.current_round || 0 }} / {{ activeTask.total_rounds || 5 }} 轮</small><small v-else>{{ busyHint }}</small></div><button v-if="taskIsActive && canWrite" class="secondary-action" type="button" @click="cancelActiveRequirementTask">取消任务</button></div>
    <div v-if="roundRetryBusy" class="requirement-progress requirement-progress--round" role="status" aria-live="polite" aria-busy="true"><span class="loading-ring"></span><div><b>第 {{ retryingRound }} 轮重试中</b><span>已等待 {{ busyElapsedLabel }}</span><small>正在等待模型完成结构化分段；按钮暂时不可重复点击。</small></div></div>
    <div v-if="selectedDocument && hasAnalysisRecords" class="requirement-record-toolbar"><button class="danger-action" :disabled="busy || !canWrite" @click="clearAnalysisRecords">清除分析记录</button><small>仅清除分析结果，需求原文、文件和解析证据会保留。</small></div>
    <div v-if="selectedDocument?.source_type === 'screenshot'" class="requirement-notice" role="status"><button class="secondary-action" :disabled="busy || !canWrite || (!selectedDocument.file_path && !selectedDocument.content_text)" @click="action(analyzeRequirementScreenshot, '截图视觉分析完成')">{{ screenshotReport?.analysis_method === 'model_verified' ? '重新视觉分析' : '截图视觉分析' }}</button><span v-if="screenshotReport"> {{ screenshotReport.analysis_method === 'model_verified' ? '模型视觉结果' : 'OCR 基线结果' }} · 证据 {{ screenshotReport.text_blocks?.length || 0 }} 条 · 置信度 {{ Math.round((screenshotReport.confidence || 0) * 100) }}%<span v-if="screenshotReport.needs_confirmation"> · 待人工确认</span></span><ul v-if="screenshotReport?.test_points?.length"><li v-for="item in screenshotReport.test_points" :key="item.id">{{ item.description }}</li></ul></div>
    <div v-if="selectedDocument && modelOptions" class="requirement-model-choice requirement-model-choice--top"><label><span>{{ selectedDocument.source_type === 'screenshot' ? '视觉分析模型' : '需求分析模型' }}</span><select v-model="modelChoice" :disabled="modelOptionsLoading || busy"><option value="">继承平台全局默认</option><option v-for="model in modelOptions.models" :key="model.id" :value="String(model.id)">{{ model.name }} · {{ model.model_name }}（{{ model.model_type_label }}）</option></select></label><small v-if="modelOptions.effective_model">当前生效：{{ modelOptions.effective_model.name }} · {{ modelOptions.effective_model.model_name }}（{{ modelOptions.effective_source === 'global' ? '平台全局默认' : '功能绑定' }}）</small><small v-if="modelOptions.route_error" class="requirement-error">{{ modelOptions.route_error }}</small><small>本次选择只对当前分析生效；有视觉模型时执行真实视觉结构化调用，未配置时明确显示 OCR 基线结果。</small></div>
    <div class="page-title-row"><div><p class="workspace-eyebrow">REQUIREMENT INTELLIGENCE</p><h1>需求智能分析</h1><p class="workspace-lead">导入需求文档，逐步完成解析、功能拆解、联合识别和测试点确认。</p></div><button class="primary-action" :disabled="loading" @click="openCreate">＋ 导入需求</button></div>
    <div v-if="notice" class="requirement-notice" role="status">{{ notice }}</div><div v-if="skillExecution" class="requirement-skill-status" role="status">本次自动调用：<b>{{ skillExecution.skill }}</b> · v{{ skillExecution.version }} · {{ skillStatusText[skillExecution.status] || skillExecution.status }}<span v-if="skillExecution.message"> · {{ skillExecution.message }}</span></div><div v-if="selectedDocument?.latest_analysis?.coverage_report?.model_route?.candidates?.length" class="requirement-source-meta">实际模型：{{ selectedDocument.latest_analysis.coverage_report.model_route.candidates[0].name }} · 调用阶段：{{ selectedDocument.latest_analysis.coverage_report.call_stage || '需求分析' }} · {{ modelVerificationLabel }}</div><div v-if="qualityBanner" :class="qualityBanner.className" role="status"><b>{{ qualityBanner.title }}</b> · {{ qualityBanner.detail }}</div><section v-if="analysisProgress || selectedDocument?.latest_analysis?.coverage_report?.round_count" class="requirement-round-panel" aria-labelledby="requirement-round-title"><div class="requirement-round-heading"><div><h2 id="requirement-round-title">五轮递进复核</h2><p>语义轮次与技术分段分别统计；只有五轮全部完成并通过质量门禁，结果才可进入人工审核。</p></div><span class="requirement-round-status">{{ roundStatusText[analysisProgress?.round_progress?.status || selectedDocument?.latest_analysis?.coverage_report?.round_execution_status] || '待执行' }}</span></div><div v-if="analysisProgressError" class="requirement-error" role="alert">{{ analysisProgressError }}</div><div v-if="analysisProgress?.round_progress" class="requirement-round-summary">分析轮次：第 {{ analysisProgress.round_progress.current_round || 0 }} / {{ analysisProgress.round_progress.total_rounds || 5 }} 轮 · 实际调用 {{ selectedDocument?.latest_analysis?.coverage_report?.total_calls || 0 }} 次</div><div class="requirement-round-list"><article v-for="round in (analysisProgress?.rounds || selectedDocument?.latest_analysis?.coverage_report?.rounds || [])" :key="round.round" class="requirement-round-card"><header><b>第 {{ round.round }} 轮 · {{ round.name }}</b><span>{{ roundStatusText[round.status] || round.status }}</span></header><p>{{ round.focus }}</p><small>分段 {{ round.completed_segments || 0 }} / {{ round.segment_count || 0 }} · 调用 {{ round.calls || 0 }} · 新增 {{ round.added || 0 }} · 修正 {{ round.updated || 0 }} · 重复 {{ round.duplicate || 0 }} · 冲突 {{ round.conflict || 0 }} · 未覆盖证据 {{ (round.uncovered_evidence || []).length }}</small><div v-if="round.failure_reason" class="requirement-error">{{ round.failure_reason }}<button v-if="['failed', 'partial', 'blocked'].includes(round.status) && canWrite" class="text-action" :disabled="busy || roundRetryBusy" @click="retryRound(round)">重试本轮</button></div></article></div><details v-if="analysisProgress?.history?.length > 1" class="requirement-round-history"><summary>查看历史轮次轨迹（{{ analysisProgress.history.length }} 次）</summary><div v-for="item in analysisProgress.history" :key="item.id">{{ item.created_at }} · {{ roundStatusText[item.round_execution_status] || item.round_execution_status }} · 完成 {{ item.completed_rounds }} / {{ item.round_count }} 轮 · 调用 {{ item.total_calls || 0 }} 次</div></details></section><div v-if="error" class="requirement-error" role="alert">{{ error }}<span v-if="failureMeta?.code">（错误码：{{ failureMeta.code }}）</span><button v-if="failureMeta?.retryable && lastAction" class="text-action" :disabled="busy" @click="retryLastAction">重试当前操作</button><button class="text-action" @click="refresh">刷新页面</button></div>
    <section v-if="analysisReview" class="requirement-review-panel" aria-labelledby="analysis-review-title">
      <div class="requirement-review-heading"><div><h2 id="analysis-review-title">审核最终需求分析结果</h2><p>这里审核的不是需求文档标题，也不是功能标题，而是大模型根据本文档产出的“模块 → 功能点 → 测试点”结果。最终测试点是主要审核对象；证据列表用于判断分析是否有原文依据。</p></div><span class="requirement-review-status">{{ analysisConfirmed ? '已确认' : '待确认' }}</span></div>
      <div class="requirement-review-scope"><span>需求文档（仅用于定位）</span><b>→</b><span>原文证据（依据）</span><b>→</b><span>功能模块 / 功能点（分析结果）</span><b>→</b><span>最终测试点（审核对象）</span><b>→</b><span>测试用例（审核通过后生成）</span></div>
      <div v-if="analysisReview.mappingGapGroups.length" class="requirement-review-blocker"><b>当前结果不能直接审核</b><span>这份分析结果缺少模块或功能点名称、测试点描述、归属关系或测试类型，不需要你手工填写编号。请点击下方“重新执行深度分析”，系统会重新生成可读且完整的审核清单。</span></div>
      <div class="requirement-review-grid">
        <article><h3>原文覆盖检查（辅助）<small>未覆盖 {{ analysisReview.uncoveredEvidence.length }} / {{ analysisReview.totalEvidence }}</small></h3><p class="requirement-review-description">作用：检查解析出的原文片段里，是否有需求没有被模型分析出来。这里不是审核功能模块；勾选表示“我已核对这条原文片段”。</p><ul v-if="analysisReview.uncoveredEvidence.length"><li v-for="item in analysisReview.uncoveredEvidence" :key="item.id"><label class="requirement-review-check"><input type="checkbox" :value="String(item.id)" v-model="reviewedEvidenceIds"><span><b>{{ item.type || '证据' }}</b> · {{ item.text || item.content || item.id }}</span></label></li></ul><p v-else class="requirement-empty requirement-empty--compact">没有未覆盖证据。</p></article>
        <article><h3>模型依据检查（辅助）<small>未引用 {{ analysisReview.uncitedItems.length }}</small></h3><p class="requirement-review-description">作用：检查模型产出的分析对象是否说明了原文依据。这里不是新的需求清单；没有依据时，优先重新分析，勾选只表示“我已看到并接受这个提示”。</p><ul v-if="analysisReview.uncitedItems.length"><li v-for="(item, index) in analysisReview.uncitedItems" :key="`${item.group}-${index}`"><label class="requirement-review-check"><input type="checkbox" :value="String(item.id)" v-model="reviewedAnalysisItemIds"><span><b>{{ item.group }}</b> · {{ item.label }} · 未提供证据引用</span></label></li></ul><p v-else class="requirement-empty requirement-empty--compact">所有分析项均提供了证据引用。</p></article>
         <article class="requirement-review-points-card"><h3>待审核测试点（主要审核对象）<small>{{ pendingReviewPoints.length }} 条</small></h3><p class="requirement-review-description">按测试点清单逐行审核：确认它属于哪个模块和功能点、描述是否准确、测试类型是否合理。勾选后点击“标记所选为已审核”，已审核测试点会从待审核表移入下方已审核数据框，并成为用例生成范围。</p><div v-if="pendingReviewPoints.length && !analysisReview.mappingGapGroups.length" class="requirement-review-points-table-wrap"><table class="requirement-review-points-table"><thead><tr><th>审核</th><th>序号</th><th>功能模块</th><th>功能点</th><th>测试点描述</th><th>测试类型</th><th>原文依据</th></tr></thead><tbody><tr v-for="(item, index) in pendingReviewPoints" :key="item.id"><td><input type="checkbox" :aria-label="`选择第${index + 1}条测试点`" :value="String(item.id)" v-model="selectedTestPointIds"></td><td>{{ index + 1 }}</td><td>{{ item.moduleLabel }}</td><td>{{ item.functionLabel }}</td><td>{{ item.description || item.scenario || '未命名测试点' }}</td><td><span class="requirement-review-type">{{ item.typeLabel }}</span></td><td>{{ item.evidenceLabels.length ? item.evidenceLabels.join('；') : '无证据引用' }}</td></tr></tbody></table></div><p v-else-if="!analysisReview.mappingGapGroups.length" class="requirement-empty requirement-empty--compact">当前没有待审核测试点；已审核测试点已移入下方数据框。</p><p v-else class="requirement-review-invalid-points">当前结果尚未形成可审核的最终测试点清单。请先重新执行深度分析，生成完整的模块名称、功能点名称、测试点描述和测试类型；这里不需要手工补写编号。</p></article>
       </div>
       <div v-if="!analysisReview.mappingGapGroups.length && analysisReview.reviewPoints.length" class="requirement-review-selection-bar">
         <div><b>已审核测试点：{{ approvedReviewPoints.length }} / {{ analysisReview.reviewPoints.length }} · 待审核 {{ pendingReviewPoints.length }}</b><small>勾选测试点后点击“标记所选为已审核”，已审核集合会保存并提供给用例生成。</small></div>
         <div class="requirement-review-selection-actions"><button class="text-action" type="button" :disabled="busy" @click="allReviewPointsSelected ? clearReviewPointSelection() : selectAllReviewPoints()">{{ allReviewPointsSelected ? '取消全选' : '全部勾选' }}</button><button class="secondary-action" type="button" :disabled="busy || !selectedTestPointIds.length" @click="markSelectedTestPointsReviewed">{{ analysisConfirmed ? '保存已审核集合' : '标记所选为已审核' }}</button></div>
       </div>
       <div v-if="approvedReviewPoints.length" class="requirement-approved-points" role="status"><h3>已审核测试点<small>{{ approvedReviewPoints.length }} 条</small></h3><ul><li v-for="(item, index) in approvedReviewPoints" :key="item.id"><b>{{ index + 1 }}.</b><span>{{ item.description || item.scenario || '未命名测试点' }}</span><small>{{ item.moduleLabel }} · {{ item.functionLabel }} · {{ item.typeLabel }}</small></li></ul></div>
       <div v-if="analysisReview.mappingGapGroups.length" class="requirement-review-mapping-error">
        <div class="requirement-review-mapping-heading"><b>分析结构与分类问题</b><span>共 {{ analysisReview.mappingGapGroups.reduce((total, group) => total + group.items.length, 0) }} 项</span></div>
        <p>以下是模型实际产出的功能点、联合场景和测试点，不是让你手工填写的 ID。它们没有形成可靠的“模块 → 功能点 → 测试点”归属，或没有标注测试类型，不能通过勾选确认，请重新执行深度分析。</p>
        <div class="requirement-review-mapping-groups"><section v-for="group in analysisReview.mappingGapGroups" :key="group.label" class="requirement-review-mapping-group"><header><b>{{ group.label }}</b><span>{{ group.items.length }} 项</span></header><div class="requirement-review-object-list"><div v-for="item in group.items" :key="item.id" class="requirement-review-object-card"><b>{{ item.title }}</b><small>{{ item.detail }}</small></div></div></section></div>
      </div>
       <section v-if="analysisReview.conflicts.length" class="requirement-review-conflicts" aria-label="五轮合并冲突人工复核">
        <h3>五轮合并冲突（必须人工复核）<small>{{ analysisReview.conflicts.length }} 条</small></h3>
        <p class="requirement-review-description">系统已保留先前有效值，没有静默覆盖。请逐条核对新旧值及来源轮次；勾选后才允许确认分析结果。</p>
        <ul><li v-for="item in analysisReview.conflicts" :key="item.reviewId"><label class="requirement-review-check"><input type="checkbox" :value="item.reviewId" v-model="reviewedConflictIds"><span><b>{{ item.collection }} · {{ item.entity_id || item.incoming_id || '未命名对象' }}</b> · 第{{ item.round || '?' }}轮 · {{ item.reason }}<small>{{ item.fieldSummary }}</small></span></label></li></ul>
       </section>
       <p v-if="analysisReview.drops.length" class="requirement-error">相对上一版数量减少：{{ analysisReview.drops.join('、') }}。请重点核对本次减少的模块、功能点和测试点。</p>
      <div class="requirement-review-actions"><button class="primary-action" :disabled="busy || !canWrite || (!selectedTestPointIds.length && !reviewedTestPointIds.length)" @click="confirmAnalysis">{{ confirmButtonLabel }}</button><button class="secondary-action" :disabled="busy || !canWrite" @click="action(analyzeRequirementDocument, '需求深度分析完成')">重新执行深度分析</button><small>{{ analysisReview.mappingGapGroups.length ? '请先重新执行深度分析，补齐模块归属和测试类型后再审核。' : reviewReady ? '审核清单已逐项确认，确认后可生成用例。' : '可单独勾选测试点后确认；全部清单完成后才会把整份分析标记为最终确认。' }} 确认不会删除需求原文或证据。</small></div>
    </section>
    <div class="requirement-toolbar"><label>项目<select v-model="selectedProject" @change="loadDocuments"><option v-for="item in projects" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><button class="secondary-action" @click="refresh">刷新</button></div>
    <section v-if="loading" class="state-panel"><span class="loading-ring"></span><b>正在加载需求文档</b></section>
    <section v-else class="requirement-layout"><aside class="requirement-panel"><div class="requirement-heading"><h2>需求文档</h2><span>{{ documents.length }}</span></div><div v-if="!projects.length" class="requirement-empty requirement-empty--action"><b>还没有项目</b><p>需求文档必须归属于已有项目，请先到“项目与智能体”创建项目。</p><button class="primary-action" @click="openCreate">前往项目管理</button></div><div v-else-if="!documents.length" class="requirement-empty">暂无需求文档，请从右上角导入。</div><button v-for="item in documents" :key="item.id" class="requirement-document" :class="{ active: item.id === selectedDocument?.id }" @click="selectedDocument = item"><b>{{ item.title }}</b><small>v{{ item.version }} · {{ item.status_label }}</small></button></aside>
      <main class="requirement-panel"><div v-if="!selectedDocument" class="requirement-empty">选择需求文档后开始分析。</div><template v-else><div class="requirement-heading"><div><h2>{{ selectedDocument.title }}</h2><small>{{ selectedDocument.source_type_label }} · {{ selectedDocument.status_label }}</small></div><button class="danger-action" :disabled="busy || !canWrite" @click="removeDocument">删除</button></div><div v-if="selectedDocument.parse_warnings?.length" class="requirement-error" role="alert"><b>来源解析需要处理：</b><span v-for="warning in selectedDocument.parse_warnings" :key="warning">{{ warning }}</span></div><div v-if="selectedDocument.parse_confidence !== undefined" class="requirement-source-meta">来源证据 {{ selectedDocument.parse_evidence?.length || 0 }} 条 · 解析置信度 {{ Math.round((selectedDocument.parse_confidence || 0) * 100) }}%<span v-if="selectedDocument.parse_confidence < 0.75"> · 待人工确认</span></div><div class="requirement-actions"><button class="secondary-action" :disabled="busy || !canWrite" @click="action(parseRequirementDocument, '文档解析完成')">解析</button><button class="primary-action" :disabled="busy || !canWrite" @click="action(analyzeRequirementDocument, '需求深度分析完成')">深度分析</button><button class="secondary-action" :disabled="busy || !canWrite || !selectedDocument.latest_analysis" @click="action(identifyRequirementLinkages, '联合功能识别完成')">联合识别</button></div><div v-if="selectedDocument.latest_analysis" class="analysis-grid"><article><h3>功能模块（{{ selectedDocument.latest_analysis.modules.length }}）</h3><ul><li v-for="item in selectedDocument.latest_analysis.modules" :key="item.id">{{ item.name }}<small v-if="item.needs_confirmation"> · 待确认</small></li></ul></article><article><h3>功能点（{{ selectedDocument.latest_analysis.functions.length }}）</h3><ul><li v-for="item in selectedDocument.latest_analysis.functions" :key="item.id">{{ item.name }}<small v-if="item.needs_confirmation"> · 待确认</small></li></ul></article><article><h3>联合场景（{{ selectedDocument.latest_analysis.linkages.length }}）</h3><p v-if="selectedDocument.latest_analysis.coverage_report.analysis_method === 'deterministic_evidence_baseline'" class="requirement-error">当前联合场景来自历史确定性基线，不能代表真实跨功能联动；请配置模型后重新执行深度分析。</p><div v-if="selectedDocument.latest_analysis.linkages.length"><ul><li v-for="item in selectedDocument.latest_analysis.linkages" :key="item.id">{{ item.description || item.relationship }}</li></ul></div><p v-else class="requirement-empty requirement-empty--compact">当前需求未发现跨模块联动。请补充两个以上模块及明确的依赖、状态或数据关系后重试。</p></article><article><h3>测试点（{{ selectedDocument.latest_analysis.test_points.length }}）</h3><p v-if="selectedDocument.latest_analysis.coverage_report.analysis_method === 'deterministic_evidence_baseline'" class="requirement-error"><b>当前分析未调用大模型。</b>这是确定性基线结果，不能直接代表真实需求覆盖；请先配置可用模型后重新执行深度分析。</p><p v-else-if="selectedDocument.latest_analysis.coverage_report.needs_confirmation" class="requirement-error">当前结果需要确认来源内容后再生成用例。</p><ul><li v-for="(item, index) in visibleTestPoints" :key="index">{{ item.description || item.type }}<small v-if="item.needs_confirmation"> · 待确认</small></li></ul><div v-if="visibleTestPointCount < selectedDocument.latest_analysis.test_points.length" class="requirement-list-more"><small>为保持页面流畅，当前显示 {{ visibleTestPoints.length }} / {{ selectedDocument.latest_analysis.test_points.length }} 条测试点。</small><button class="text-action" type="button" @click="loadMoreTestPoints">加载更多</button></div></article></div><div v-else class="requirement-empty">尚未生成分析结果，请先解析后执行深度分析。</div></template></main></section>
    <div v-if="showForm" class="modal-backdrop" @click.self="!busy && (showForm = false)"><section class="config-modal requirement-modal"><header><h2>导入需求文档</h2><button @click="showForm = false">×</button></header><div class="config-form"><label>标题<input v-model="form.title" maxlength="500"></label><label>版本<input v-model="form.version" maxlength="20"></label><label>来源<select v-model="form.source_type"><option value="manual">手工录入</option><option value="file">文档文件</option><option value="screenshot">截图 OCR</option><option value="online_link">在线链接</option></select></label><label v-if="form.source_type === 'online_link'">链接<input v-model="form.source_url" placeholder="https://..."></label><label v-if="form.source_type === 'manual' || form.source_type === 'screenshot'">{{ form.source_type === 'screenshot' ? 'OCR 正文（可选）' : '正文' }}<textarea v-model="form.content_text" rows="8"></textarea></label><label v-if="['file', 'screenshot'].includes(form.source_type)">文件<input type="file" accept=".txt,.md,.markdown,.pdf,.docx,.xlsx,.json,.png,.jpg,.jpeg,.webp" @change="onFile"><small>单个文件最大 10MB，超过限制会在本地先提示。</small></label><p v-if="formError" class="form-error" role="alert">{{ formError }}</p></div><footer><button class="secondary-action" @click="showForm = false">取消</button><button class="primary-action" :disabled="busy" @click="saveDocument">{{ busy ? '保存中…' : '创建文档' }}</button></footer></section></div>
    <div v-if="selectedDocument?.latest_analysis?.coverage_report?.structured_generation?.status === 'completed'" class="requirement-source-meta" role="status">结构化分段已完成：{{ selectedDocument.latest_analysis.coverage_report.structured_generation.completed_segments }} / {{ selectedDocument.latest_analysis.coverage_report.structured_generation.segment_count }} 段，结果已合并去重。</div><div v-else-if="selectedDocument?.latest_analysis?.coverage_report?.structured_generation?.status === 'partial'" class="requirement-error" role="alert">结构化分析部分完成：已保留 {{ selectedDocument.latest_analysis.coverage_report.structured_generation.completed_segments }} 个分段，失败分段可通过重新执行深度分析恢复；当前结果不能视为完整模型验证。</div>
    <div v-if="selectedDocument?.latest_analysis?.coverage_report?.analysis_method === 'model_partial'" class="requirement-error" role="alert">当前需求分析只完成了部分分段，不能直接用于完整用例生成，请修复失败段后重新执行。</div>
    <div v-if="selectedDocument?.latest_analysis?.coverage_report?.structured_generation?.status === 'failed'" class="requirement-error" role="alert">结构化分析首段调用失败：已完成 {{ selectedDocument.latest_analysis.coverage_report.structured_generation.completed_segments || 0 }} / {{ selectedDocument.latest_analysis.coverage_report.structured_generation.segment_count || 0 }} 段；错误码 {{ selectedDocument.latest_analysis.coverage_report.error_code || 'model_error' }}，请修复模型配置后重试。</div>
  </div></WorkspaceShell>
</template>
