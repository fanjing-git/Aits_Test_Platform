<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  createModelConfig,
  deleteModelConfig,
  getModelCatalog,
  getModelUsage,
  listModelConfigs,
  testModelConnection,
  updateModelConfig,
} from '../api/models'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'

const typeLabels = { chat: '对话模型', embedding: '向量模型', vision: '视觉模型' }

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

const form = reactive(defaultForm())
const activeCount = computed(() => models.value.filter((item) => item.is_active).length)
const defaultCount = computed(() => models.value.filter((item) => item.is_default).length)
const selectedProvider = computed(() => catalog.value.find((item) => item.value === form.provider))
const availableTypes = computed(() => selectedProvider.value?.types || Object.entries(typeLabels).map(([value, label]) => ({ value, label, models: [] })))
const selectedType = computed(() => availableTypes.value.find((item) => item.value === form.model_type))
const suggestedModels = computed(() => selectedType.value?.models || [])
const hasModelSuggestions = computed(() => suggestedModels.value.length > 0)

function defaultForm() {
  return {
    name: '', provider: 'openai', model_name: '', model_type: 'chat', api_key: '',
    api_base_url: '', parametersText: '{\n  "temperature": 0.2\n}', is_default: false,
    is_active: true, priority: 100,
  }
}

async function loadCatalog() {
  catalogLoading.value = true
  try {
    const result = await getModelCatalog()
    catalog.value = result.providers || []
  } catch {
    // The form still works with the three generic model types if catalog is unavailable.
  } finally {
    catalogLoading.value = false
  }
}

function handleProviderChange() {
  const firstType = availableTypes.value[0]
  form.model_type = firstType?.value || 'chat'
  form.model_name = ''
  customModelName.value = ''
}

function handleTypeChange() {
  form.model_name = ''
  customModelName.value = ''
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
}

function openEdit(model) {
  const providerCatalog = catalog.value.find((item) => item.value === model.provider)
  const knownModel = providerCatalog?.types?.some((type) => type.models.includes(model.model_name))
  Object.assign(form, {
    name: model.name, provider: model.provider, model_name: knownModel ? model.model_name : '__custom__',
    model_type: model.model_type, api_key: '', api_base_url: model.api_base_url,
    parametersText: JSON.stringify(model.parameters || {}, null, 2),
    is_default: model.is_default, is_active: model.is_active, priority: model.priority,
  })
  customModelName.value = knownModel ? '' : model.model_name
  editingId.value = model.id
  formError.value = ''
  showForm.value = true
}

async function saveModel() {
  formError.value = ''
  if (!form.name.trim() || !form.model_name.trim()) {
    formError.value = '请填写配置名称和模型名称。'
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
    model_name: (form.model_name === '__custom__' ? customModelName.value : form.model_name).trim(),
    model_type: form.model_type, api_base_url: form.api_base_url.trim(), parameters,
    is_default: form.is_default, is_active: form.is_active, priority: Number(form.priority),
  }
  if (!editingId.value || form.api_key !== '') payload.api_key = form.api_key

  saving.value = true
  try {
    if (editingId.value) await updateModelConfig(editingId.value, payload)
    else await createModelConfig(payload)
    ElMessage.success(editingId.value ? '模型配置已更新' : '模型配置已创建')
    showForm.value = false
    await loadModels()
  } catch (error) {
    formError.value = apiError(error, '保存失败，请检查填写内容后重试。')
  } finally {
    saving.value = false
  }
}

async function testConnection(model) {
  testingId.value = model.id
  try {
    const result = await testModelConnection(model.id)
    ElMessage.success(`${result.message}${result.latency_ms ? `（${result.latency_ms}ms）` : ''}`)
  } catch (error) {
    ElMessage.warning(apiError(error, '连接测试失败，请检查配置或联系管理员启用适配器。'))
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
  await Promise.all([loadModels(), loadCatalog()])
})
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
        <button class="primary-action" @click="openCreate">＋ 添加模型</button>
      </div>

      <section class="model-summary" aria-label="模型配置概览">
        <article><small>全部配置</small><strong>{{ models.length }}</strong><span>个模型接入点</span></article>
        <article><small>当前启用</small><strong>{{ activeCount }}</strong><span>可参与任务路由</span></article>
        <article><small>默认模型</small><strong>{{ defaultCount }}</strong><span>按能力类型统计</span></article>
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
                <td><span class="type-chip">{{ typeLabels[model.model_type] }}</span></td>
                <td><span :class="['status-chip', model.is_active ? 'is-online' : 'is-offline']"><i></i>{{ model.is_active ? '已启用' : '已停用' }}</span></td>
                <td><b class="priority-value">P{{ model.priority }}</b><small v-if="model.is_default" class="default-label">默认</small></td>
                <td><span>{{ model.has_api_key ? '已安全配置' : '无需或未配置' }}</span></td>
                <td><div class="row-actions"><button @click="openEdit(model)">编辑</button><button :disabled="testingId === model.id" @click="testConnection(model)">{{ testingId === model.id ? '测试中' : '测试连接' }}</button><button @click="showUsage(model)">用量</button><button class="danger" @click="deleteTarget = model">删除</button></div></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <Teleport to="body">
    <div v-if="showForm" class="modal-backdrop" @click.self="showForm = false">
      <section class="config-modal" role="dialog" aria-modal="true" aria-labelledby="model-form-title" @click.stop>
        <header><div><small>{{ editingId ? 'EDIT MODEL' : 'NEW MODEL' }}</small><h2 id="model-form-title">{{ editingId ? '编辑模型配置' : '添加模型配置' }}</h2></div><button aria-label="关闭" @click="showForm = false">×</button></header>
        <div class="config-form">
          <label><span>配置名称 *</span><input v-model="form.name" placeholder="例如：主对话模型"></label>
          <div class="form-row"><label><span>提供商 *</span><select v-model="form.provider" :disabled="catalogLoading" @change="handleProviderChange"><option v-for="option in catalog" :key="option.value" :value="option.value">{{ option.label }}</option></select></label><label><span>模型类型 *</span><select v-model="form.model_type" @change="handleTypeChange"><option v-for="option in availableTypes" :key="option.value" :value="option.value">{{ option.label }}</option></select></label></div>
          <label><span>模型名称 *</span><select v-if="hasModelSuggestions" v-model="form.model_name"><option value="">请选择模型</option><option v-for="modelName in suggestedModels" :key="modelName" :value="modelName">{{ modelName }}</option><option value="__custom__">＋ 自定义模型名称</option></select><input v-if="!hasModelSuggestions || form.model_name === '__custom__'" v-model="customModelName" placeholder="输入部署名称或自定义模型名"><small v-if="hasModelSuggestions">已加载 {{ suggestedModels.length }} 个推荐模型，也可以选择“自定义模型名称”。</small><small v-else>当前供应商未提供固定目录，请输入部署名称或自定义模型名。</small></label>
          <label><span>API 地址</span><input v-model="form.api_base_url" placeholder="留空则使用提供商默认地址"></label>
          <label><span>API Key</span><input v-model="form.api_key" type="password" :placeholder="editingId ? '留空表示保留现有密钥' : '本地模型可留空'" autocomplete="new-password"><small>密钥只会提交一次并加密保存，页面不会读取或回显。</small></label>
          <label><span>模型参数（JSON）</span><textarea v-model="form.parametersText" rows="5" spellcheck="false"></textarea></label>
          <div class="form-row"><label><span>路由优先级</span><input v-model.number="form.priority" type="number" min="0"></label><div class="toggle-group"><label><input v-model="form.is_active" type="checkbox"> 启用配置</label><label><input v-model="form.is_default" type="checkbox"> 设为该类型默认模型</label></div></div>
          <p v-if="formError" class="form-error">{{ formError }}</p>
        </div>
        <footer><button class="secondary-action" @click="showForm = false">取消</button><button class="primary-action" :disabled="saving" @click="saveModel">{{ saving ? '正在保存…' : '保存配置' }}</button></footer>
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
