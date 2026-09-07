<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  createModelConfig,
  deleteModelConfig,
  getModelCatalog,
  discoverModels,
  getModelUsage,
  listModelConfigs,
  listRoutingMatrix,
  testModelConnection,
  upsertRoutingPolicy,
  updateModelConfig,
} from '../api/models'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'
import { loadAllModelPages, resolveModelName } from '../utils/modelCatalog'
import { routeSourceLabel, routingPayload } from '../utils/modelRouting'

const typeLabels = { chat: '文本对话与推理', embedding: '向量', vision: '图像 / 视频理解', multimodal: '全模态', image_generation: '图像生成与编辑', video: '视频生成', audio: '音频理解与生成', tts: '语音合成', asr: '语音识别', realtime: '实时交互', rerank: '重排序', three_d: '三维生成', other: '其他 / 待确认能力' }

const models = ref([])
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const testingId = ref(null)
const showForm = ref(false)
const editingId = ref(null)
const formError = ref('')
const deleteTarget = ref(null)
const usage = ref(null)
const usageModel = ref(null)
const usageLoading = ref(false)
const customModelName = ref('')
const catalog = ref([])
const catalogLoading = ref(false)
const catalogError = ref('')
const discoveryLoading = ref(false)
const discoveryError = ref('')
const discoveryMessage = ref('')
const liveModels = ref(null)
const modelSearch = ref('')
const showAllModels = ref(true)
const credentialConfigId = ref(null)
const testTarget = ref(null)
const testMode = ref('catalog')
const testResult = ref(null)
const routingMatrix = ref([])
const routingLoading = ref(true)
const routingError = ref('')
const routingSaving = ref('')
const routingSaved = reactive({})
let discoveryEpoch = 0

const form = reactive(defaultForm())
const activeCount = computed(() => models.value.filter((item) => item.is_active).length)
const defaultCount = computed(() => models.value.filter((item) => item.is_default).length)
const selectedProvider = computed(() => catalog.value.find((item) => item.value === form.provider))
const availableTypes = computed(() => {
  const result = new Map((selectedProvider.value?.types || []).map((item) => [item.value, item]))
  for (const model of liveModels.value || []) {
    for (const value of model.types) if (typeLabels[value]) result.set(value, { value, label: typeLabels[value] })
  }
  if (!result.has(form.model_type)) result.set(form.model_type, { value: form.model_type, label: typeLabels[form.model_type] || form.model_type })
  return [...result.values()]
})
const providerModels = computed(() => liveModels.value ?? selectedProvider.value?.models ?? [])
const suggestedModels = computed(() => providerModels.value.filter((item) =>
  (showAllModels.value || item.types.includes(form.model_type) || item.types.includes('other'))
  && `${item.id} ${item.label}`.toLowerCase().includes(modelSearch.value.trim().toLowerCase())))
const canProbe = computed(() => ['chat', 'vision', 'embedding'].includes(testTarget.value?.model_type))

function defaultForm() {
  return {
    name: '', provider: 'openai', model_name: '', model_type: 'chat', api_key: '',
    api_base_url: '', parametersText: '{\n  "temperature": 0.2\n}', is_default: false,
    is_active: true, priority: 100,
  }
}

async function loadCatalog() {
  catalogLoading.value = true
  catalogError.value = ''
  try {
    const result = await getModelCatalog()
    catalog.value = result.providers || []
  } catch (error) {
    catalogError.value = apiError(error, '供应商目录加载失败，请重试。')
  } finally {
    catalogLoading.value = false
  }
}

function handleProviderChange() {
  resetDiscovery()
  const firstType = availableTypes.value[0]
  form.model_type = firstType?.value || 'chat'
  form.model_name = ''
  customModelName.value = ''
  form.api_key = ''
  const saved = models.value.find((item) => item.provider === form.provider && item.has_api_key)
  form.api_base_url = saved?.api_base_url || selectedProvider.value?.default_base_url || ''
  credentialConfigId.value = saved?.id || null
  syncModels()
}

function handleTypeChange() {
  modelSearch.value = ''
  showAllModels.value = false
  const selected = providerModels.value.find((item) => item.id === form.model_name)
  if (selected && !selected.types.includes('other') && !selected.types.includes(form.model_type)) form.model_name = ''
}

function resetDiscovery() {
  discoveryEpoch++
  discoveryLoading.value = false
  liveModels.value = null
  discoveryError.value = ''
  discoveryMessage.value = ''
  modelSearch.value = ''
  showAllModels.value = true
}

function handleEndpointChange() {
  resetDiscovery()
  credentialConfigId.value = null
  if (!form.api_key) discoveryMessage.value = '地址已变化，请重新输入对应密钥后同步。'
  else syncModels()
}

function handleKeyChange() {
  resetDiscovery()
  syncModels()
}

async function syncModels() {
  const epoch = ++discoveryEpoch
  if (!form.api_key && !credentialConfigId.value && !['local', 'custom'].includes(form.provider)) {
    discoveryMessage.value = '填写 API Key 后自动同步供应商完整目录；当前仅展示公开参考目录。'
    return
  }
  const payload = { provider: form.provider, api_base_url: form.api_base_url }
  if (form.api_key) payload.api_key = form.api_key
  else if (credentialConfigId.value) payload.config_id = credentialConfigId.value
  discoveryLoading.value = true
  discoveryError.value = ''
  liveModels.value = []
  let loadedCount = 0
  try {
    await loadAllModelPages(discoverModels, payload, (items, hasNext) => {
      liveModels.value = items
      loadedCount = items.length
      discoveryMessage.value = `已加载 ${loadedCount} 个模型${hasNext ? '，正在读取下一页…' : '，目录同步完成。'}`
    }, () => epoch === discoveryEpoch && showForm.value)
  } catch (error) {
    if (epoch !== discoveryEpoch) return
    if (!loadedCount) liveModels.value = null
    discoveryError.value = apiError(error, error.message || '目录同步失败，请重试。')
    discoveryMessage.value = loadedCount ? `仅加载 ${loadedCount} 个模型，目录不完整。` : '同步未完成，显示公开参考目录；可重试或填写自定义模型。'
  } finally {
    if (epoch === discoveryEpoch) discoveryLoading.value = false
  }
}

function selectModel() {
  const selected = providerModels.value.find((item) => item.id === form.model_name)
  if (selected && !selected.types.includes('other') && !selected.types.includes(form.model_type)) form.model_type = selected.types[0]
}

function closeForm() {
  resetDiscovery()
  showForm.value = false
}

function apiError(error, fallback) {
  const data = error.response?.data
  if (typeof data?.detail === 'string') return data.detail
  if (typeof data?.message === 'string') return data.message
  if (data && typeof data === 'object') {
    const first = Object.entries(data)[0]
    if (first) return `${first[0]}：${Array.isArray(first[1]) ? first[1][0] : first[1]}`
  }
  return fallback
}

function providerLabel(value) {
  return catalog.value.find((item) => item.value === value)?.label || value
}

async function loadModels() {
  loading.value = true
  loadError.value = ''
  try {
    models.value = await listModelConfigs()
  } catch (error) {
    loadError.value = apiError(error, '模型配置加载失败，请确认后端服务后重试。')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, defaultForm())
  customModelName.value = ''
  editingId.value = null
  formError.value = ''
  showForm.value = true
  handleProviderChange()
}

function openEdit(model) {
  resetDiscovery()
  Object.assign(form, {
    name: model.name, provider: model.provider, model_name: '__custom__',
    model_type: model.model_type, api_key: '', api_base_url: model.api_base_url,
    parametersText: JSON.stringify(model.parameters || {}, null, 2),
    is_default: model.is_default, is_active: model.is_active, priority: model.priority,
  })
  customModelName.value = model.model_name
  credentialConfigId.value = model.id
  editingId.value = model.id
  formError.value = ''
  showForm.value = true
  syncModels()
}

async function saveModel() {
  formError.value = ''
  const resolvedName = resolveModelName(form.model_name, customModelName.value)
  if (!form.name.trim() || !resolvedName) {
    formError.value = '请填写配置名称和模型名称。'
    return
  }
  if (!editingId.value && !form.api_key.trim() && !['local', 'custom'].includes(form.provider)) {
    formError.value = '新建配置请填写 API Key；目录同步使用的已有密钥不会复制到新配置。'
    return
  }
  let parameters
  try {
    parameters = JSON.parse(form.parametersText || '{}')
    if (!parameters || Array.isArray(parameters) || typeof parameters !== 'object') throw new Error()
  } catch {
    formError.value = '模型参数必须是有效的 JSON 对象。'
    return
  }
  const payload = {
    name: form.name.trim(), provider: form.provider,
    model_name: resolvedName,
    model_type: form.model_type, api_base_url: form.api_base_url.trim(), parameters,
    is_default: form.is_default, is_active: form.is_active, priority: Number(form.priority),
  }
  if (!editingId.value || form.api_key !== '') payload.api_key = form.api_key

  saving.value = true
  try {
    if (editingId.value) await updateModelConfig(editingId.value, payload)
    else await createModelConfig(payload)
    ElMessage.success(editingId.value ? '模型配置已更新' : '模型配置已创建')
    closeForm()
    await loadModels()
  } catch (error) {
    formError.value = apiError(error, '保存失败，请检查填写内容后重试。')
  } finally {
    saving.value = false
  }
}

function openConnectionTest(model) {
  testTarget.value = model
  testMode.value = 'catalog'
  testResult.value = null
}

async function loadRoutingMatrix() {
  routingLoading.value = true
  routingError.value = ''
  try {
    routingMatrix.value = await listRoutingMatrix()
    for (const row of routingMatrix.value) routingSaved[row.feature_key] = Boolean(row.id)
  } catch (error) {
    routingError.value = apiError(error, '模型路由策略加载失败，请确认管理员权限后重试。')
  } finally {
    routingLoading.value = false
  }
}

async function saveRouting(row) {
  routingSaving.value = row.feature_key
  routingError.value = ''
  try {
    await upsertRoutingPolicy(routingPayload(row))
    ElMessage.success(`${row.feature_label}路由策略已保存`)
    await loadRoutingMatrix()
    routingSaved[row.feature_key] = true
  } catch (error) {
    routingError.value = apiError(error, '路由策略保存失败，请检查模型能力和权限。')
  } finally {
    routingSaving.value = ''
  }
}

function markRoutingDirty(row) {
  routingSaved[row.feature_key] = false
}

function routingButtonLabel(row) {
  return routingSaved[row.feature_key] ? '大模型已保存' : '保存此大模型'
}

function modelLabel(model) {
  if (!model) return '未配置'
  return `${model.name} · ${model.model_name}`
}

function modelTypeLabel(type) {
  return typeLabels[type] || type
}

async function testConnection() {
  const model = testTarget.value
  if (!model || testingId.value) return
  testingId.value = model.id
  testResult.value = null
  try {
    testResult.value = await testModelConnection(model.id, testMode.value)
  } catch (error) {
    testResult.value = { ok: false, message: apiError(error, '连接测试失败，请检查地址、凭据和网络后重试。') }
  } finally {
    testingId.value = null
  }
}

async function showUsage(model) {
  usageModel.value = model
  usage.value = null
  usageLoading.value = true
  try {
    usage.value = await getModelUsage(model.id)
  } catch (error) {
    ElMessage.error(apiError(error, '用量统计加载失败。'))
    usageModel.value = null
  } finally {
    usageLoading.value = false
  }
}

async function confirmDelete() {
  const model = deleteTarget.value
  if (!model) return
  try {
    await deleteModelConfig(model.id)
    ElMessage.success(`已删除“${model.name}”`)
    deleteTarget.value = null
    await loadModels()
  } catch (error) {
    ElMessage.error(apiError(error, '删除失败，该配置可能仍被其他功能使用。'))
  }
}

onMounted(async () => {
  await Promise.all([loadModels(), loadCatalog(), loadRoutingMatrix()])
})
onBeforeUnmount(() => { discoveryEpoch++ })
</script>

<template>
  <WorkspaceShell active="models">
    <div class="workspace-content model-page">
      <div class="page-title-row">
        <div>
          <p class="workspace-eyebrow">PLATFORM MODEL CONTROL</p>
          <h1>模型配置</h1>
          <p class="workspace-lead">统一管理智能体使用的模型、凭据、优先级和调用情况。</p>
        </div>
        <button class="primary-action" :disabled="catalogLoading || !catalog.length" @click="openCreate">＋ 添加模型</button>
      </div>

      <p v-if="catalogError" class="form-error" role="alert">{{ catalogError }} <button class="text-action" @click="loadCatalog">重新加载目录</button></p>
      <section class="model-summary" aria-label="模型配置概览">
        <article><small>全部配置</small><strong>{{ models.length }}</strong><span>个模型接入点</span></article>
        <article><small>当前启用</small><strong>{{ activeCount }}</strong><span>可参与任务路由</span></article>
        <article><small>默认模型</small><strong>{{ defaultCount }}</strong><span>按能力类型统计</span></article>
      </section>

      <section class="model-panel routing-panel">
        <div class="panel-heading"><div><h2>平台模型路由</h2><p>未单独绑定的功能继承全局默认；模型列表已按功能能力过滤。</p></div><button class="text-action" :disabled="routingLoading" @click="loadRoutingMatrix">刷新</button></div>
        <div v-if="routingLoading" class="state-panel"><span class="loading-ring"></span><b>正在读取路由策略</b><p>请稍候，平台正在计算每个功能的生效模型。</p></div>
        <div v-else-if="routingError && !routingMatrix.length" class="state-panel state-panel--error"><b>路由策略暂时不可用</b><p>{{ routingError }}</p><button @click="loadRoutingMatrix">重新加载</button></div>
        <div v-else-if="!routingMatrix.length" class="state-panel"><b>没有可配置的路由功能</b><p>请确认后端路由策略接口已启用。</p></div>
        <div v-else class="routing-grid">
          <article v-for="row in routingMatrix" :key="row.feature_key" class="routing-card">
            <header><div><b>{{ row.feature_label }}</b><small>需要：{{ row.required_model_types.map(modelTypeLabel).join(' / ') }}</small></div><span v-if="row.feature_key === 'global'" class="default-label">平台级</span></header>
            <div class="routing-effective" :class="{ 'routing-effective--error': row.route_error }">
              <small>当前生效</small><b>{{ modelLabel(row.effective_model) }}</b><span>{{ row.route_error || routeSourceLabel(row.effective_source) }}</span>
            </div>
            <label><span>{{ row.feature_key === 'global' ? '平台全局默认模型' : '功能模型（可继承全局）' }}</span><select v-model="row.primary_model_id" @change="markRoutingDirty(row)"><option :value="null">{{ row.feature_key === 'global' ? '暂不设置全局模型' : '继承平台全局默认' }}</option><option v-for="model in row.available_models" :key="model.id" :value="model.id">{{ model.name }} · {{ model.model_name }}（{{ modelTypeLabel(model.model_type) }}）</option></select></label>
            <label><span>备用模型（可选）</span><select v-model="row.backup_model_id" @change="markRoutingDirty(row)"><option :value="null">不配置备用模型</option><option v-for="model in row.available_models" :key="`backup-${model.id}`" :value="model.id">{{ model.name }} · {{ model.model_name }}</option></select></label>
            <div class="routing-switches"><label><input v-model="row.allow_fallback" type="checkbox" @change="markRoutingDirty(row)"> 允许调用失败时切换备用</label><label><input v-model="row.allow_deterministic_baseline" type="checkbox" @change="markRoutingDirty(row)"> 允许用户主动选择确定性基线</label></div>
            <p v-if="row.feature_key !== 'global' && row.inherits_global" class="routing-hint">当前功能继承平台全局模型；单独选择后将覆盖全局配置。</p>
            <p v-if="row.route_error" class="form-error" role="alert">{{ row.route_error }}</p>
            <button :class="['secondary-action', 'routing-save', { 'routing-save--saved': routingSaved[row.feature_key] }]" :disabled="routingSaving === row.feature_key || routingSaved[row.feature_key]" @click="saveRouting(row)">{{ routingSaving === row.feature_key ? '保存中…' : routingButtonLabel(row) }}</button>
          </article>
        </div>
        <p v-if="routingError && routingMatrix.length" class="form-error" role="alert">{{ routingError }}</p>
      </section>

      <section class="model-panel">
        <div class="panel-heading"><div><h2>模型接入列表</h2><p>默认模型优先参与路由；数字越小，备用优先级越高。</p></div><button class="text-action" @click="loadModels">刷新</button></div>
        <div v-if="loading" class="state-panel"><span class="loading-ring"></span><b>正在读取模型配置</b><p>请稍候，平台正在同步最新状态。</p></div>
        <div v-else-if="loadError" class="state-panel state-panel--error"><b>暂时无法加载</b><p>{{ loadError }}</p><button @click="loadModels">重新加载</button></div>
        <div v-else-if="!models.length" class="state-panel"><b>还没有模型配置</b><p>添加第一个模型后，智能体才能根据任务类型选择运行模型。</p><button @click="openCreate">添加模型</button></div>
        <div v-else class="model-table-wrap">
          <table class="model-table">
            <thead><tr><th>配置 / 模型</th><th>类型</th><th>接入状态</th><th>路由</th><th>凭据</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="model in models" :key="model.id">
                <td><b>{{ model.name }}</b><small>{{ providerLabel(model.provider) }} · {{ model.model_name }}</small></td>
                <td><span class="type-chip">{{ typeLabels[model.model_type] || model.model_type }}</span></td>
                <td><span :class="['status-chip', model.is_active ? 'is-online' : 'is-offline']"><i></i>{{ model.is_active ? '已启用' : '已停用' }}</span></td>
                <td><b class="priority-value">P{{ model.priority }}</b><small v-if="model.is_default" class="default-label">默认</small></td>
                <td><span>{{ model.has_api_key ? '已安全配置' : '无需或未配置' }}</span></td>
                <td><div class="row-actions"><button @click="openEdit(model)">编辑</button><button :disabled="testingId !== null" @click="openConnectionTest(model)">{{ testingId === model.id ? '测试中' : '测试连接' }}</button><button @click="showUsage(model)">用量</button><button class="danger" @click="deleteTarget = model">删除</button></div></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <Teleport to="body">
    <div v-if="showForm" class="modal-backdrop" @click.self="closeForm">
      <section class="config-modal" role="dialog" aria-modal="true" aria-labelledby="model-form-title" @click.stop>
        <header><div><small>{{ editingId ? 'EDIT MODEL' : 'NEW MODEL' }}</small><h2 id="model-form-title">{{ editingId ? '编辑模型配置' : '添加模型配置' }}</h2></div><button aria-label="关闭" @click="closeForm">×</button></header>
        <div class="config-form">
          <label><span>配置名称 *</span><input v-model="form.name" placeholder="例如：主对话模型"></label>
          <div class="form-row"><label><span>提供商 *</span><select v-model="form.provider" :disabled="catalogLoading" @change="handleProviderChange"><option v-for="option in catalog" :key="option.value" :value="option.value">{{ option.label }}</option></select></label><label><span>模型类型 *</span><select v-model="form.model_type" @change="handleTypeChange"><option v-for="option in availableTypes" :key="option.value" :value="option.value">{{ option.label }}</option></select></label></div>
          <label><span>API 地址</span><input v-model="form.api_base_url" placeholder="供应商 API 基础地址" @input="resetDiscovery" @change="handleEndpointChange"></label>
          <div v-if="form.provider === 'qwen'" class="catalog-note">
            <b>千问接入地址须与密钥地域、业务空间一致</b>
            <p>北京新业务空间：https://业务空间ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1；存量北京地址可使用 dashscope.aliyuncs.com，新加坡可使用 dashscope-intl.aliyuncs.com。</p>
            <p>Coding Plan 请填写控制台给出的专用地址。不要将专用 Key 与普通百炼地址混用。</p>
            <a href="https://www.alibabacloud.com/help/zh/model-studio/regions/" target="_blank" rel="noopener noreferrer">查看官方地域与地址说明</a>
          </div>
          <label><span>API Key</span><input v-model="form.api_key" type="password" :placeholder="editingId ? '留空表示保留现有密钥' : '输入密钥以加载供应商目录'" autocomplete="new-password" @input="resetDiscovery" @change="handleKeyChange"><small>密钥仅用于后端同步和测试；保存时加密，页面不读取或回显已有密钥。</small></label>
          <div class="catalog-note" aria-live="polite">
            <div class="catalog-toolbar"><b>{{ discoveryLoading ? '正在同步供应商模型…' : '供应商模型目录' }}</b><button type="button" class="text-action" :disabled="discoveryLoading" @click="syncModels">{{ discoveryLoading ? '同步中…' : '刷新模型目录' }}</button></div>
            <p v-if="credentialConfigId && !form.api_key">同步使用已有配置的加密密钥；新建配置仍须填写自己的 API Key 后保存。</p>
            <p>{{ discoveryMessage || '选择供应商后自动加载目录。' }}</p>
            <p v-if="liveModels === null">公开参考目录（非完整账号清单）。参考日期：{{ selectedProvider?.updated_at }}。<a v-if="selectedProvider?.source_url" :href="selectedProvider.source_url" target="_blank" rel="noopener noreferrer">供应商官方目录</a></p>
            <p v-if="discoveryError" class="form-error" role="alert">{{ discoveryError }}</p>
            <p v-if="liveModels !== null && !providerModels.length && !discoveryLoading && !discoveryError">供应商返回空目录。请检查地域、模型授权，或填写实际部署名称。</p>
          </div>
          <label><span>搜索模型</span><input v-model="modelSearch" placeholder="按名称或模型 ID 搜索"></label>
          <label class="catalog-checkbox"><input v-model="showAllModels" type="checkbox"> 显示全部类型的模型（未标注能力的模型也会保留）</label>
          <label><span>模型名称 *</span><select v-model="form.model_name" @change="selectModel"><option value="">请选择模型</option><option v-for="model in suggestedModels" :key="model.id" :value="model.id">{{ model.id }} · {{ model.types.map((type) => typeLabels[type] || type).join(' / ') }}</option><option value="__custom__">＋ 自定义模型 / Azure 部署名称</option></select><input v-if="form.model_name === '__custom__'" v-model="customModelName" placeholder="输入准确的模型 ID 或部署名称"><small>当前显示 {{ suggestedModels.length }} / {{ providerModels.length }} 个模型。能力未标注时请按供应商说明选择类型；目录可见不等于已开通调用权限。</small><small v-if="!suggestedModels.length && modelSearch">没有匹配项，请调整搜索或使用自定义名称。</small></label>
          <label><span>模型参数（JSON）</span><textarea v-model="form.parametersText" rows="5" spellcheck="false"></textarea></label>
          <div class="form-row"><label><span>路由优先级</span><input v-model.number="form.priority" type="number" min="0"></label><div class="toggle-group"><label><input v-model="form.is_active" type="checkbox"> 启用配置</label><label><input v-model="form.is_default" type="checkbox"> 设为该类型默认模型</label></div></div>
          <p v-if="formError" class="form-error">{{ formError }}</p>
        </div>
        <footer><button class="secondary-action" @click="closeForm">取消</button><button class="primary-action" :disabled="saving" @click="saveModel">{{ saving ? '正在保存…' : '保存配置' }}</button></footer>
      </section>
    </div>

    <div v-if="testTarget" class="modal-backdrop" @click.self="!testingId && (testTarget = null)">
      <section class="config-modal" role="dialog" aria-modal="true" aria-labelledby="connection-title">
        <header><h2 id="connection-title">连接测试 · {{ testTarget.name }}</h2><button :disabled="testingId !== null" aria-label="关闭" @click="testTarget = null">×</button></header>
        <div class="config-form">
          <label><span>测试方式</span><select v-model="testMode" :disabled="testingId !== null"><option value="catalog">目录连接与模型可见性（不调用生成）</option><option v-if="canProbe" value="inference">所选模型实际调用（可能产生少量费用）</option></select></label>
          <p>{{ testMode === 'catalog' ? '检查供应商目录和所选模型。目录不支持或使用 Azure 部署名时，可改用实际调用测试。' : '发送一次简短文本或向量请求，不发送项目数据；失败不自动重试。视觉模型使用文本探测，不代表图片理解验收通过。' }}</p>
          <p v-if="!canProbe">此类型支持目录连接测试；专用媒体生成或实时会话需要对应输入，当前不自动发起这些任务。</p>
          <p v-if="testingId" role="status">正在测试，请稍候…</p>
          <div v-if="testResult" class="catalog-note" :class="{ 'form-error': !testResult.ok }" role="status"><b>{{ testResult.ok ? '测试通过' : '测试未通过' }}</b><p>{{ testResult.message }}</p><small v-if="testResult.latency_ms">耗时 {{ testResult.latency_ms }} ms</small></div>
        </div>
        <footer><button class="secondary-action" :disabled="testingId !== null" @click="testTarget = null">关闭</button><button class="primary-action" :disabled="testingId !== null" @click="testConnection">{{ testingId ? '测试中…' : testResult ? '重新测试' : '开始测试' }}</button></footer>
      </section>
    </div>

    <div v-if="usageModel" class="modal-backdrop" @click.self="usageModel = null">
      <section class="usage-modal" role="dialog" aria-modal="true"><header><div><small>MODEL USAGE</small><h2>{{ usageModel.name }} · 用量统计</h2></div><button @click="usageModel = null">×</button></header><div v-if="usageLoading" class="state-panel">正在加载统计…</div><div v-else-if="usage" class="usage-grid"><article><span>调用总数</span><b>{{ usage.calls }}</b></article><article><span>成功 / 失败</span><b>{{ usage.successful_calls }} / {{ usage.failed_calls }}</b></article><article><span>Token 总量</span><b>{{ usage.total_tokens.toLocaleString() }}</b><small>输入 {{ usage.input_tokens }} · 输出 {{ usage.output_tokens }}</small></article><article><span>累计费用</span><b>{{ usage.cost }}</b><small>按模型上报数据汇总</small></article></div></section>
    </div>

    <div v-if="deleteTarget" class="modal-backdrop" @click.self="deleteTarget = null">
      <section class="confirm-modal" role="alertdialog" aria-modal="true"><span class="danger-mark">!</span><h2>删除模型配置？</h2><p>将删除“{{ deleteTarget.name }}”及其用量记录。依赖该模型的功能可能无法运行，此操作不可撤销。</p><div><button class="secondary-action" @click="deleteTarget = null">取消</button><button class="danger-action" @click="confirmDelete">确认删除</button></div></section>
    </div>
    </Teleport>
  </WorkspaceShell>
</template>
