<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  createPromptConfig,
  deletePromptConfig,
  getPromptHistory,
  listPromptConfigs,
  previewPromptConfig,
  rollbackPromptConfig,
  updatePromptConfig,
} from '../api/prompts'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'

const scopeOptions = [
  ['global', '全局默认'], ['project', '项目级'], ['scene', '场景级'], ['instant', '即时指定'],
]
const sceneOptions = [
  ['default', '全局默认'], ['requirement_analysis', '需求分析'], ['case_gen', '用例生成'],
  ['case_review', '用例评审'], ['api_test', '接口测试'], ['ai_test', 'AI 测试'],
  ['ui_test', 'UI 测试'], ['app_test', 'APP 测试'], ['perf_test', '性能测试'],
  ['screenshot_analysis', '截图识别'], ['report_gen', '报告生成'],
]

const prompts = ref([])
const loading = ref(true)
const loadError = ref('')
const filters = reactive({ scope: '', scene_type: '' })
const showForm = ref(false)
const editing = ref(null)
const saving = ref(false)
const formError = ref('')
const previewTarget = ref(null)
const previewVariables = ref('{}')
const previewResult = ref('')
const previewError = ref('')
const previewing = ref(false)
const historyTarget = ref(null)
const historyItems = ref([])
const historyLoading = ref(false)
const rollingVersion = ref(null)
const deleteTarget = ref(null)

const form = reactive(defaultForm())
const sceneCount = computed(() => new Set(prompts.value.map((item) => item.scene_type)).size)
const customCount = computed(() => prompts.value.filter((item) => item.version > 1).length)

function defaultForm() {
  return { name: '', scope: 'scene', scene_type: 'default', content: '', variablesText: '{}', is_active: true }
}

function apiError(error, fallback) {
  const data = error.response?.data
  if (typeof data?.detail === 'string') return data.detail
  if (data && typeof data === 'object') {
    const first = Object.entries(data)[0]
    if (first) return `${first[0]}：${Array.isArray(first[1]) ? first[1][0] : first[1]}`
  }
  return fallback
}

async function loadPrompts() {
  loading.value = true
  loadError.value = ''
  try {
    prompts.value = await listPromptConfigs({
      ...(filters.scope && { scope: filters.scope }),
      ...(filters.scene_type && { scene_type: filters.scene_type }),
    })
  } catch (error) {
    loadError.value = apiError(error, '提示词配置加载失败，请确认服务状态后重试。')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, defaultForm())
  editing.value = null
  formError.value = ''
  showForm.value = true
}

function openEdit(prompt) {
  editing.value = prompt
  Object.assign(form, {
    name: prompt.name,
    scope: prompt.scope,
    scene_type: prompt.scene_type,
    content: prompt.content,
    variablesText: JSON.stringify(prompt.variables || {}, null, 2),
    is_active: prompt.is_active,
  })
  formError.value = ''
  showForm.value = true
}

function parseVariables(text) {
  const value = JSON.parse(text || '{}')
  if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error()
  return value
}

async function savePrompt() {
  formError.value = ''
  if (!form.name.trim() || !form.content.trim()) {
    formError.value = '请填写配置名称和提示词内容。'
    return
  }
  let variables
  try { variables = parseVariables(form.variablesText) } catch {
    formError.value = '模板变量必须是有效的 JSON 对象。'
    return
  }
  const payload = {
    name: form.name.trim(), scope: form.scope, scene_type: form.scene_type,
    content: form.content.trim(), variables, is_active: form.is_active,
  }
  saving.value = true
  try {
    if (editing.value) await updatePromptConfig(editing.value.id, payload)
    else await createPromptConfig(payload)
    ElMessage.success(editing.value ? '已保存为新的提示词版本' : '提示词配置已创建')
    showForm.value = false
    await loadPrompts()
  } catch (error) {
    formError.value = apiError(error, '保存失败，请检查配置内容。')
  } finally { saving.value = false }
}

function openPreview(prompt) {
  previewTarget.value = prompt
  previewVariables.value = JSON.stringify(prompt.variables || {}, null, 2)
  previewResult.value = ''
  previewError.value = ''
}

async function runPreview() {
  previewError.value = ''
  let variables
  try { variables = parseVariables(previewVariables.value) } catch {
    previewError.value = '测试变量必须是有效的 JSON 对象。'
    return
  }
  previewing.value = true
  try {
    const result = await previewPromptConfig(previewTarget.value.id, variables)
    previewResult.value = result.rendered_content
  } catch (error) {
    previewError.value = apiError(error, '预览失败，请检查模板变量。')
  } finally { previewing.value = false }
}

async function openHistory(prompt) {
  historyTarget.value = prompt
  historyItems.value = []
  historyLoading.value = true
  try { historyItems.value = await getPromptHistory(prompt.id) } catch (error) {
    ElMessage.error(apiError(error, '版本历史加载失败。'))
    historyTarget.value = null
  } finally { historyLoading.value = false }
}

async function rollback(version) {
  rollingVersion.value = version
  try {
    await rollbackPromptConfig(historyTarget.value.id, version)
    ElMessage.success(`已基于 v${version} 创建新的生效版本`)
    historyTarget.value = null
    await loadPrompts()
  } catch (error) {
    ElMessage.error(apiError(error, '回滚失败，请刷新后重试。'))
  } finally { rollingVersion.value = null }
}

async function confirmDelete() {
  try {
    await deletePromptConfig(deleteTarget.value.id)
    ElMessage.success(`已删除“${deleteTarget.value.name}”当前版本`)
    deleteTarget.value = null
    await loadPrompts()
  } catch (error) { ElMessage.error(apiError(error, '删除失败。')) }
}

onMounted(loadPrompts)
</script>

<template>
  <WorkspaceShell active="prompts">
    <div class="workspace-content model-page prompt-page">
      <div class="page-title-row">
        <div><p class="workspace-eyebrow">PROMPT ORCHESTRATION LAYER</p><h1>提示词配置</h1><p class="workspace-lead">管理全局、项目、场景与即时四级指令，所有编辑均保留版本记录。</p></div>
        <button class="primary-action" @click="openCreate">＋ 新建提示词</button>
      </div>

      <section class="model-summary" aria-label="提示词配置概览">
        <article><small>当前生效</small><strong>{{ prompts.length }}</strong><span>条提示词配置</span></article>
        <article><small>覆盖场景</small><strong>{{ sceneCount }}</strong><span>类测试与分析场景</span></article>
        <article><small>已有新版本</small><strong>{{ customCount }}</strong><span>条配置经过编辑或回滚</span></article>
      </section>

      <section class="prompt-filters">
        <label><span>作用层级</span><select v-model="filters.scope" @change="loadPrompts"><option value="">全部层级</option><option v-for="option in scopeOptions" :key="option[0]" :value="option[0]">{{ option[1] }}</option></select></label>
        <label><span>业务场景</span><select v-model="filters.scene_type" @change="loadPrompts"><option value="">全部场景</option><option v-for="option in sceneOptions" :key="option[0]" :value="option[0]">{{ option[1] }}</option></select></label>
        <button class="text-action" @click="loadPrompts">刷新配置</button>
      </section>

      <section class="model-panel">
        <div class="panel-heading"><div><h2>生效提示词</h2><p>优先级：即时指定 ＞ 场景级 ＞ 项目级 ＞ 全局默认。</p></div></div>
        <div v-if="loading" class="state-panel"><span class="loading-ring"></span><b>正在解析提示词层级</b><p>请稍候，平台正在读取当前生效版本。</p></div>
        <div v-else-if="loadError" class="state-panel state-panel--error"><b>暂时无法加载</b><p>{{ loadError }}</p><button @click="loadPrompts">重新加载</button></div>
        <div v-else-if="!prompts.length" class="state-panel"><b>当前筛选下没有配置</b><p>可以调整筛选条件，或创建一条新的提示词。</p><button @click="openCreate">新建提示词</button></div>
        <div v-else class="prompt-grid">
          <article v-for="prompt in prompts" :key="prompt.id" class="prompt-card">
            <header><div><span :class="['scope-chip', `scope-chip--${prompt.scope}`]">{{ prompt.scope_label }}</span><span class="scene-chip">{{ prompt.scene_type_label }}</span></div><b>v{{ prompt.version }}</b></header>
            <h3>{{ prompt.name }}</h3><p>{{ prompt.content }}</p>
            <div class="prompt-variables"><small>模板变量</small><code>{{ Object.keys(prompt.variables || {}).length ? Object.keys(prompt.variables).join(' · ') : '无' }}</code></div>
            <footer class="row-actions"><button @click="openEdit(prompt)">编辑</button><button @click="openPreview(prompt)">测试预览</button><button @click="openHistory(prompt)">版本历史</button><button class="danger" @click="deleteTarget = prompt">删除</button></footer>
          </article>
        </div>
      </section>
    </div>

    <div v-if="showForm" class="modal-backdrop" @click.self="showForm = false"><section class="config-modal prompt-form-modal" role="dialog" aria-modal="true"><header><div><small>{{ editing ? 'NEW VERSION' : 'NEW PROMPT' }}</small><h2>{{ editing ? `编辑 ${editing.name}` : '新建提示词配置' }}</h2></div><button @click="showForm = false">×</button></header><div class="config-form"><label><span>配置名称 *</span><input v-model="form.name" placeholder="例如：接口测试团队规范"></label><div class="form-row"><label><span>作用层级</span><select v-model="form.scope"><option v-for="option in scopeOptions" :key="option[0]" :value="option[0]">{{ option[1] }}</option></select></label><label><span>业务场景</span><select v-model="form.scene_type"><option v-for="option in sceneOptions" :key="option[0]" :value="option[0]">{{ option[1] }}</option></select></label></div><label><span>提示词内容 *</span><textarea v-model="form.content" rows="10" placeholder="输入角色、规则和输出要求；变量使用 {{ variable }} 格式。"></textarea></label><label><span>模板变量（JSON）</span><textarea v-model="form.variablesText" rows="5" spellcheck="false"></textarea><small>编辑现有配置会创建新版本，不会覆盖历史记录。</small></label><div class="toggle-group"><label><input v-model="form.is_active" type="checkbox"> 保存后立即启用</label></div><p v-if="formError" class="form-error">{{ formError }}</p></div><footer><button class="secondary-action" @click="showForm = false">取消</button><button class="primary-action" :disabled="saving" @click="savePrompt">{{ saving ? '正在保存…' : '保存配置' }}</button></footer></section></div>

    <div v-if="previewTarget" class="modal-backdrop" @click.self="previewTarget = null"><section class="config-modal prompt-preview-modal" role="dialog" aria-modal="true"><header><div><small>PROMPT SANDBOX</small><h2>测试预览 · {{ previewTarget.name }}</h2></div><button @click="previewTarget = null">×</button></header><div class="config-form"><label><span>测试变量（JSON）</span><textarea v-model="previewVariables" rows="6" spellcheck="false"></textarea></label><p v-if="previewError" class="form-error">{{ previewError }}</p><div v-if="previewResult" class="preview-output"><small>渲染结果</small><pre>{{ previewResult }}</pre></div></div><footer><button class="secondary-action" @click="previewTarget = null">关闭</button><button class="primary-action" :disabled="previewing" @click="runPreview">{{ previewing ? '正在渲染…' : '生成预览' }}</button></footer></section></div>

    <div v-if="historyTarget" class="modal-backdrop" @click.self="historyTarget = null"><section class="usage-modal history-modal" role="dialog" aria-modal="true"><header><div><small>VERSION TIMELINE</small><h2>{{ historyTarget.name }} · 版本历史</h2></div><button @click="historyTarget = null">×</button></header><div v-if="historyLoading" class="state-panel">正在读取历史版本…</div><div v-else class="history-list"><article v-for="item in historyItems" :key="item.id"><div><b>v{{ item.version }}</b><span :class="['status-chip', item.is_active ? 'is-online' : 'is-offline']"><i></i>{{ item.is_active ? '当前生效' : '历史版本' }}</span></div><p>{{ item.content }}</p><button v-if="!item.is_active" :disabled="rollingVersion === item.version" @click="rollback(item.version)">{{ rollingVersion === item.version ? '正在回滚…' : `回滚到 v${item.version}` }}</button></article></div></section></div>

    <div v-if="deleteTarget" class="modal-backdrop" @click.self="deleteTarget = null"><section class="confirm-modal" role="alertdialog" aria-modal="true"><span class="danger-mark">!</span><h2>删除当前提示词？</h2><p>将删除“{{ deleteTarget.name }}”的当前生效版本。历史版本仍会保留，但该层级可能暂时失去生效配置。</p><div><button class="secondary-action" @click="deleteTarget = null">取消</button><button class="danger-action" @click="confirmDelete">确认删除</button></div></section></div>
  </WorkspaceShell>
</template>
