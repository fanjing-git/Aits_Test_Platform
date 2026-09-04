<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import * as agentApi from '../api/agents'
import * as projectApi from '../api/projects'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'

const projects = ref([])
const selectedId = ref('')
const members = ref([])
const candidates = ref([])
const agents = ref([])
const options = ref({ models: [], prompts: [] })
const loading = ref(true)
const detailLoading = ref(false)
const error = ref('')
const tab = ref('agents')
const projectModal = ref(false)
const agentModal = ref(false)
const historyModal = ref(false)
const deleteTarget = ref(null)
const editingProject = ref(null)
const editingAgent = ref(null)
const history = ref([])
const historyTarget = ref(null)
const saving = ref(false)
const formError = ref('')
const memberChoice = ref('')
const memberRole = ref('member')

const projectForm = reactive({ name: '', description: '', status: 'active', settingsText: '{}' })
const agentForm = reactive({ name: '', description: '', agent_type: 'general', model_config_id: '', prompt_config_id: '', knowledgeText: '', skillsText: '', parametersText: '{}', status: 'draft' })
const selected = computed(() => projects.value.find((item) => item.id === selectedId.value) || null)
const canEdit = computed(() => ['owner', 'manager', 'platform_admin'].includes(selected.value?.current_role))
const canDelete = computed(() => ['owner', 'platform_admin'].includes(selected.value?.current_role))
const activeAgents = computed(() => agents.value.filter((item) => item.status === 'active').length)

function apiError(err, fallback) {
  const data = err.response?.data
  if (typeof data?.detail === 'string') return data.detail
  if (data && typeof data === 'object') {
    const [key, value] = Object.entries(data)[0] || []
    if (key) return `${key}：${Array.isArray(value) ? value[0] : value}`
  }
  return fallback
}

async function loadProjects(preferId = '') {
  loading.value = true
  error.value = ''
  try {
    projects.value = await projectApi.listProjects()
    selectedId.value = projects.value.some((p) => p.id === preferId)
      ? preferId
      : (projects.value.some((p) => p.id === selectedId.value) ? selectedId.value : projects.value[0]?.id || '')
  } catch (err) { error.value = apiError(err, '项目列表加载失败，请检查服务状态。') }
  finally { loading.value = false }
}

async function loadDetails() {
  if (!selected.value) { members.value = []; agents.value = []; return }
  detailLoading.value = true
  try {
    const requests = [projectApi.listProjectMembers(selectedId.value), agentApi.listAgents({ project: selectedId.value }), agentApi.getAgentOptions()]
    if (canEdit.value) requests.push(projectApi.listMemberCandidates(selectedId.value))
    const [memberData, agentData, optionData, candidateData = []] = await Promise.all(requests)
    members.value = memberData
    agents.value = agentData
    options.value = optionData
    candidates.value = candidateData
  } catch (err) { ElMessage.error(apiError(err, '项目详情加载失败。')) }
  finally { detailLoading.value = false }
}

watch(selectedId, loadDetails)

function openProject(project = null) {
  editingProject.value = project
  Object.assign(projectForm, project ? {
    name: project.name, description: project.description, status: project.status,
    settingsText: JSON.stringify(project.settings || {}, null, 2),
  } : { name: '', description: '', status: 'active', settingsText: '{}' })
  formError.value = ''; projectModal.value = true
}

async function saveProject() {
  if (!projectForm.name.trim()) { formError.value = '请填写项目名称。'; return }
  let settings
  try { settings = JSON.parse(projectForm.settingsText || '{}'); if (!settings || Array.isArray(settings)) throw new Error() }
  catch { formError.value = '项目设置必须是有效的 JSON 对象。'; return }
  saving.value = true; formError.value = ''
  try {
    const payload = { name: projectForm.name.trim(), description: projectForm.description.trim(), status: projectForm.status, settings }
    const saved = editingProject.value
      ? await projectApi.updateProject(editingProject.value.id, payload)
      : await projectApi.createProject(payload)
    projectModal.value = false
    ElMessage.success(editingProject.value ? '项目已更新' : '项目已创建，你已自动成为所有者')
    await loadProjects(saved.id)
    await loadDetails()
  } catch (err) { formError.value = apiError(err, '项目保存失败。') }
  finally { saving.value = false }
}

async function removeProject() {
  try {
    await projectApi.deleteProject(deleteTarget.value.id)
    ElMessage.success('项目及其智能体配置已删除')
    deleteTarget.value = null
    await loadProjects()
  } catch (err) { ElMessage.error(apiError(err, '项目删除失败。')) }
}

async function addMember() {
  if (!memberChoice.value) return
  try {
    await projectApi.addProjectMember(selectedId.value, { user_id: Number(memberChoice.value), role: memberRole.value })
    memberChoice.value = ''
    ElMessage.success('成员已加入项目')
    await loadProjects(selectedId.value); await loadDetails()
  } catch (err) { ElMessage.error(apiError(err, '添加成员失败。')) }
}

async function changeMember(member, role) {
  try {
    await projectApi.updateProjectMember(selectedId.value, member.id, { role })
    ElMessage.success('成员角色已更新'); await loadDetails()
  } catch (err) { ElMessage.error(apiError(err, '角色更新失败。')); await loadDetails() }
}

async function removeMember(member) {
  if (!window.confirm(`确认移除成员“${member.user.username}”吗？`)) return
  try { await projectApi.deleteProjectMember(selectedId.value, member.id); ElMessage.success('成员已移除'); await loadProjects(selectedId.value); await loadDetails() }
  catch (err) { ElMessage.error(apiError(err, '成员移除失败。')) }
}

function openAgent(agent = null) {
  editingAgent.value = agent
  Object.assign(agentForm, agent ? {
    name: agent.name, description: agent.description, agent_type: agent.agent_type,
    model_config_id: agent.model_config_id, prompt_config_id: agent.prompt_config_id || '',
    knowledgeText: (agent.knowledge_base_ids || []).join('\n'), skillsText: (agent.skill_ids || []).join('\n'),
    parametersText: JSON.stringify(agent.parameters || {}, null, 2), status: agent.status,
  } : { name: '', description: '', agent_type: 'general', model_config_id: options.value.models[0]?.id || '', prompt_config_id: '', knowledgeText: '', skillsText: '', parametersText: '{}', status: 'draft' })
  formError.value = ''; agentModal.value = true
}

function lines(text) { return [...new Set(text.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean))] }

async function saveAgent() {
  if (!agentForm.name.trim() || !agentForm.model_config_id) { formError.value = '请填写智能体名称并选择模型配置。'; return }
  let parameters
  try { parameters = JSON.parse(agentForm.parametersText || '{}'); if (!parameters || Array.isArray(parameters)) throw new Error() }
  catch { formError.value = '运行参数必须是有效的 JSON 对象。'; return }
  const payload = {
    project_id: selectedId.value, name: agentForm.name.trim(), description: agentForm.description.trim(),
    agent_type: agentForm.agent_type, model_config_id: Number(agentForm.model_config_id),
    prompt_config_id: agentForm.prompt_config_id ? Number(agentForm.prompt_config_id) : null,
    knowledge_base_ids: lines(agentForm.knowledgeText), skill_ids: lines(agentForm.skillsText), parameters, status: agentForm.status,
  }
  saving.value = true; formError.value = ''
  try {
    const result = editingAgent.value ? await agentApi.updateAgent(editingAgent.value.id, payload) : await agentApi.createAgent(payload)
    agentModal.value = false
    ElMessage.success(editingAgent.value ? `已生成 v${result.version} 新版本` : '智能体已创建')
    await loadDetails()
  } catch (err) { formError.value = apiError(err, '智能体保存失败。') }
  finally { saving.value = false }
}

async function openHistory(agent) {
  historyTarget.value = agent; history.value = []; historyModal.value = true
  try { history.value = await agentApi.getAgentHistory(agent.id) }
  catch (err) { historyModal.value = false; ElMessage.error(apiError(err, '版本历史加载失败。')) }
}

async function rollback(version) {
  if (!window.confirm(`确认基于 v${version} 创建新的回滚版本吗？`)) return
  try { const result = await agentApi.rollbackAgent(historyTarget.value.id, version); historyModal.value = false; ElMessage.success(`已创建回滚版本 v${result.version}`); await loadDetails() }
  catch (err) { ElMessage.error(apiError(err, '版本回滚失败。')) }
}

async function removeAgent(agent) {
  if (!window.confirm(`确认删除“${agent.name}”的全部版本吗？`)) return
  try { await agentApi.deleteAgent(agent.id); ElMessage.success('智能体版本链已删除'); await loadDetails() }
  catch (err) { ElMessage.error(apiError(err, '智能体删除失败。')) }
}

onMounted(async () => { await loadProjects(); await loadDetails() })
</script>

<template>
  <WorkspaceShell active="projects">
    <div class="workspace-content project-agent-page">
      <div class="page-title-row">
        <div><p class="workspace-eyebrow">PROJECT INTELLIGENCE MATRIX</p><h1>项目与智能体</h1><p class="workspace-lead">在同一个控制面管理项目边界、协作成员和智能体版本。</p></div>
        <button class="primary-action" @click="openProject()">＋ 新建项目</button>
      </div>

      <div v-if="loading" class="state-panel"><span class="loading-ring"></span><b>正在加载项目空间</b></div>
      <div v-else-if="error" class="state-panel state-panel--error"><b>暂时无法加载</b><p>{{ error }}</p><button @click="loadProjects()">重新加载</button></div>
      <div v-else-if="!projects.length" class="state-panel empty-orbit"><b>还没有项目</b><p>创建第一个项目后，你会自动成为项目所有者，并可配置成员和智能体。</p><button @click="openProject()">创建项目</button></div>
      <div v-else class="project-console">
        <aside class="project-rail">
          <div class="rail-head"><span>项目空间</span><b>{{ projects.length }}</b></div>
          <button v-for="project in projects" :key="project.id" :class="['project-node', { active: project.id === selectedId }]" @click="selectedId = project.id">
            <i></i><span><b>{{ project.name }}</b><small>{{ project.member_count }} 位成员 · {{ project.current_role }}</small></span><em>{{ project.status }}</em>
          </button>
        </aside>

        <section v-if="selected" class="project-stage">
          <header class="project-hero">
            <div><span class="signal-label">{{ selected.status }}</span><h2>{{ selected.name }}</h2><p>{{ selected.description || '暂无项目说明' }}</p></div>
            <div class="hero-actions"><button v-if="canEdit" @click="openProject(selected)">编辑项目</button><button v-if="canDelete" class="danger" @click="deleteTarget = selected">删除项目</button></div>
          </header>
          <div class="project-metrics"><article><small>协作成员</small><b>{{ members.length }}</b></article><article><small>智能体配置</small><b>{{ agents.length }}</b></article><article><small>已启用智能体</small><b>{{ activeAgents }}</b></article><article><small>我的项目角色</small><b class="role-value">{{ selected.current_role }}</b></article></div>
          <nav class="stage-tabs"><button :class="{ active: tab === 'agents' }" @click="tab = 'agents'">智能体矩阵</button><button :class="{ active: tab === 'members' }" @click="tab = 'members'">项目成员</button></nav>

          <div v-if="detailLoading" class="state-panel compact"><span class="loading-ring"></span><b>同步项目数据</b></div>
          <section v-else-if="tab === 'agents'" class="stage-content">
            <div class="section-title"><div><h3>智能体配置</h3><p>编辑会生成新版本，历史配置不会被覆盖。</p></div><button v-if="canEdit" class="primary-action" :disabled="!options.models.length" @click="openAgent()">＋ 创建智能体</button></div>
            <div v-if="!options.models.length && canEdit" class="inline-alert">当前没有可用模型，请先由平台管理员在“模型配置”中启用模型。</div>
            <div v-if="!agents.length" class="state-panel compact"><b>该项目还没有智能体</b><p>{{ canEdit ? '选择模型与提示词，创建第一套智能体配置。' : '等待项目管理员创建智能体配置。' }}</p></div>
            <div v-else class="agent-grid">
              <article v-for="agent in agents" :key="agent.id" class="agent-card">
                <header><span>{{ agent.agent_type_label }}</span><b>v{{ agent.version }}</b></header><h4>{{ agent.name }}</h4><p>{{ agent.description || '暂无说明' }}</p>
                <dl><div><dt>状态</dt><dd :class="`status-${agent.status}`">{{ agent.status_label }}</dd></div><div><dt>知识库</dt><dd>{{ agent.knowledge_base_ids.length }}</dd></div><div><dt>技能</dt><dd>{{ agent.skill_ids.length }}</dd></div></dl>
                <footer><button v-if="canEdit" @click="openAgent(agent)">编辑</button><button @click="openHistory(agent)">版本历史</button><button v-if="canDelete" class="danger" @click="removeAgent(agent)">删除</button></footer>
              </article>
            </div>
          </section>

          <section v-else class="stage-content">
            <div class="section-title"><div><h3>项目成员</h3><p>所有者不可移除；manager 可维护配置，member/viewer 为只读。</p></div></div>
            <div v-if="canEdit" class="member-invite"><select v-model="memberChoice"><option value="">选择待加入用户</option><option v-for="user in candidates" :key="user.id" :value="user.id">{{ user.username }}{{ user.email ? ` · ${user.email}` : '' }}</option></select><select v-model="memberRole"><option value="manager">manager</option><option value="member">member</option><option value="viewer">viewer</option></select><button class="primary-action" :disabled="!memberChoice" @click="addMember">添加成员</button></div>
            <div class="member-list"><article v-for="member in members" :key="member.id"><span class="member-avatar">{{ member.user.username.slice(0, 1).toUpperCase() }}</span><div><b>{{ member.user.username }}</b><small>{{ member.user.email || '未设置邮箱' }}</small></div><select v-if="canEdit && member.role !== 'owner'" :value="member.role" @change="changeMember(member, $event.target.value)"><option value="manager">manager</option><option value="member">member</option><option value="viewer">viewer</option></select><em v-else>{{ member.role }}</em><button v-if="canEdit && member.role !== 'owner'" class="danger-link" @click="removeMember(member)">移除</button></article></div>
          </section>
        </section>
      </div>
    </div>

    <div v-if="projectModal" class="modal-backdrop"><section class="config-modal"><header><div><small>PROJECT BOUNDARY</small><h2>{{ editingProject ? '编辑项目' : '创建项目' }}</h2></div><button @click="projectModal = false">×</button></header><div class="config-form"><label>项目名称<input v-model="projectForm.name" maxlength="100" /></label><label>项目说明<textarea v-model="projectForm.description" rows="3"></textarea></label><div class="form-row"><label>状态<select v-model="projectForm.status"><option value="active">进行中</option><option value="paused">已暂停</option><option value="archived">已归档</option></select></label></div><label>扩展设置（JSON）<textarea v-model="projectForm.settingsText" rows="5" spellcheck="false"></textarea></label><p v-if="formError" class="form-error">{{ formError }}</p></div><footer><button class="secondary-action" @click="projectModal = false">取消</button><button class="primary-action" :disabled="saving" @click="saveProject">{{ saving ? '保存中…' : '确认保存' }}</button></footer></section></div>

    <div v-if="agentModal" class="modal-backdrop"><section class="config-modal agent-modal"><header><div><small>AGENT VERSION CONTROL</small><h2>{{ editingAgent ? `编辑 ${editingAgent.name} · 当前 v${editingAgent.version}` : '创建智能体' }}</h2></div><button @click="agentModal = false">×</button></header><div class="config-form"><div class="form-row"><label>智能体名称<input v-model="agentForm.name" :disabled="!!editingAgent" maxlength="100" /></label><label>智能体类型<select v-model="agentForm.agent_type"><option value="general">通用智能体</option><option value="requirement_analyst">需求分析</option><option value="case_generator">用例生成</option><option value="test_executor">测试执行</option><option value="reviewer">审核评估</option></select></label></div><label>说明<textarea v-model="agentForm.description" rows="2"></textarea></label><div class="form-row"><label>模型配置<select v-model="agentForm.model_config_id"><option value="">请选择</option><option v-for="model in options.models" :key="model.id" :value="model.id">{{ model.name }} · {{ model.provider }}/{{ model.model_name }}</option></select></label><label>提示词配置<select v-model="agentForm.prompt_config_id"><option value="">不绑定</option><option v-for="prompt in options.prompts" :key="prompt.id" :value="prompt.id">{{ prompt.name }} · v{{ prompt.version }}</option></select></label></div><div class="form-row"><label>知识库引用<small>每行一个引用 ID</small><textarea v-model="agentForm.knowledgeText" rows="4"></textarea></label><label>技能引用<small>每行一个 Skill ID</small><textarea v-model="agentForm.skillsText" rows="4"></textarea></label></div><label>运行参数（JSON）<textarea v-model="agentForm.parametersText" rows="5" spellcheck="false"></textarea></label><label>状态<select v-model="agentForm.status"><option value="draft">草稿</option><option value="active">启用</option><option value="disabled">停用</option></select></label><p v-if="formError" class="form-error">{{ formError }}</p></div><footer><button class="secondary-action" @click="agentModal = false">取消</button><button class="primary-action" :disabled="saving" @click="saveAgent">{{ saving ? '保存中…' : editingAgent ? '生成新版本' : '创建智能体' }}</button></footer></section></div>

    <div v-if="historyModal" class="modal-backdrop"><section class="config-modal history-modal"><header><div><small>IMMUTABLE HISTORY</small><h2>{{ historyTarget?.name }} · 版本历史</h2></div><button @click="historyModal = false">×</button></header><div class="history-list"><article v-for="item in history" :key="item.id"><div><b>v{{ item.version }}</b><span>{{ item.status_label }} · {{ item.agent_type_label }}</span><small>{{ new Date(item.created_at).toLocaleString() }} · {{ item.created_by.username }}</small></div><p>{{ item.description || '暂无说明' }}</p><button v-if="canEdit && item.version !== historyTarget.version" @click="rollback(item.version)">回滚到此版本</button><em v-else-if="item.version === historyTarget.version">当前版本</em></article></div></section></div>

    <div v-if="deleteTarget" class="modal-backdrop"><section class="confirm-modal"><span class="danger-mark">!</span><h2>删除项目？</h2><p>“{{ deleteTarget.name }}”及其成员关系、全部智能体版本都会被删除，此操作不可撤销。</p><div><button class="secondary-action" @click="deleteTarget = null">取消</button><button class="danger-action" @click="removeProject">确认删除</button></div></section></div>
  </WorkspaceShell>
</template>
