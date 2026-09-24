<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'
import { useUserStore } from '../stores/user'
import { listProjects } from '../api/projects'
import * as api from '../api/skills'

const userStore=useUserStore(); const isPlatformAdmin=computed(()=>userStore.user?.role==='admin'); function canManageProject(projectId){if(isPlatformAdmin.value)return true;return ['owner','manager'].includes(projects.value.find(item=>String(item.id)===String(projectId))?.current_role)} function canManageConfiguration(item){return item.layer==='global'?isPlatformAdmin.value:canManageProject(item.project||item.configuration_snapshot?.project_id)}
const skills=ref([]); const projects=ref([]); const project=ref(''); const loading=ref(true); const error=ref(''); const modal=ref(false); const editing=ref(null); const busy=ref(false); const formError=ref(''); const executeModal=ref(false); const executing=ref(false); const executeTarget=ref(null); const executeInput=ref('{}'); const executeResult=ref(''); const executeError=ref('')
const chains=ref([]); const chainLoading=ref(true); const chainError=ref(''); const chainModal=ref(false); const chainEditing=ref(null); const chainBusy=ref(false); const chainFormError=ref(''); const chainExampleSkill=ref(null); const chainForm=reactive({name:'',version:'1.0.0',description:'',project:'',definition:'{\n  "nodes": []\n}'})
const configurations=ref([]); const configLoading=ref(true); const configError=ref(''); const configModal=ref(false); const configEditing=ref(null); const configBusy=ref(false); const configFormError=ref(''); const configForm=reactive({chain:'',layer:'project',project:'',feature_key:'requirement_analysis',version_lock:'',enabled:true,max_calls:'',max_runtime_seconds:'',max_cost_units:'',allowed_data_scopes:''}); const previewForm=reactive({project:'',feature_key:'requirement_analysis',instant_chain:''}); const previewResult=ref(null); const previewLoading=ref(false); const historyModal=ref(false); const historyRows=ref([])
const versionsModal=ref(false); const versionsLoading=ref(false); const versionsError=ref(''); const versionRows=ref([]); const selectedBlueprint=ref(null); const diffResult=ref(null); const chainHistoryModal=ref(false); const chainHistoryLoading=ref(false); const chainHistoryError=ref(''); const chainHistoryRows=ref([])
const runs=ref([]); const runLoading=ref(true); const runError=ref(''); const runBusy=ref(false); const selectedRun=ref(null); const runDetailModal=ref(false)
const form=reactive({name:'',version:'1.0.0',description:'',category:'custom',project:'',triggers:'{}',capabilities:'[]',tools:'[]',knowledge:'[]',input_schema:'{}',output_schema:'{}'})
const visibleSkills=computed(()=>project.value?skills.value.filter(item=>!item.project||item.project===project.value):skills.value)
const manageableProjects=computed(()=>projects.value.filter(item=>canManageProject(item.id)))
function explain(err,fallback){if(err.response?.status===401)return'登录已过期，请重新登录。';if(err.response?.status===403)return'当前账号没有操作此 Skill 的权限。';const d=err.response?.data;if(typeof d?.detail==='string')return d.detail;const v=d&&Object.values(d)[0];return Array.isArray(v)?v.join('；'):(v||fallback)}
function previewLayerLabel(layer){if(layer.chain_name)return layer.layer_label+'：'+layer.chain_name;if(Number.isInteger(layer.count)&&layer.count>1)return layer.layer_label+'：多个配置（'+layer.count+' 条）';return layer.layer_label||'未命名范围'}
function auditActionLabel(action){return({create:'创建基线',update:'修改配置',enable:'启用配置',disable:'停用配置',rollback:'回滚配置',revoke:'撤销配置',chain_create:'创建蓝图版本',chain_update:'修改蓝图草稿',chain_fork:'派生蓝图版本',chain_verify:'校验蓝图',chain_publish:'发布蓝图',chain_enable:'启用蓝图',chain_pause:'暂停新运行',chain_archive:'归档蓝图',chain_rollback:'蓝图回滚',chain_superseded:'被新版本替代',chain_revoke:'撤销蓝图草稿'})[action]||action}
function auditRoleLabel(role){return({admin:'平台管理员',test_leader:'测试负责人',tester:'测试工程师',developer:'开发工程师',viewer:'访客',owner:'项目所有者',manager:'项目管理员',member:'项目成员'})[role]||role||'历史角色未知'}
async function loadRuns(){runLoading.value=true;runError.value='';try{runs.value=await api.listSkillChainRuns()}catch(err){runError.value=explain(err,'运行记录加载失败，请重试。')}finally{runLoading.value=false}}
async function load(){loading.value=true;chainLoading.value=true;configLoading.value=true;error.value='';chainError.value='';configError.value='';try{const [skillItems,projectItems,chainItems,configurationItems]=await Promise.all([api.listSkills(),listProjects(),api.listSkillChains(),api.listSkillChainConfigurations()]);skills.value=skillItems;projects.value=projectItems;chains.value=chainItems;configurations.value=configurationItems;previewForm.project=project.value||''}catch(err){error.value=explain(err,'Skills 加载失败，请重试。');chainError.value=explain(err,'Skill 链契约加载失败，请重试。');configError.value=explain(err,'Skill 链配置加载失败，请重试。')}finally{loading.value=false;chainLoading.value=false;configLoading.value=false}await loadRuns()}
async function refreshSkills(){if(loading.value)return;await load();if(!error.value)ElMessage.success('Skills 已刷新')}
function openForm(item=null){editing.value=item;Object.assign(form,{name:item?.name||'',version:item?.version||'1.0.0',description:item?.description||'',category:item?.category||'custom',project:item?.project||project.value||projects.value[0]?.id||'',triggers:JSON.stringify(item?.triggers||{},null,2),capabilities:JSON.stringify(item?.capabilities||[],null,2),tools:JSON.stringify(item?.tools||[],null,2),knowledge:JSON.stringify(item?.knowledge||[],null,2),input_schema:JSON.stringify(item?.input_schema||{},null,2),output_schema:JSON.stringify(item?.output_schema||{},null,2)});formError.value='';modal.value=true}
function json(text,label){try{return JSON.parse(text)}catch{formError.value=`${label}必须是有效 JSON。`;return null}}
async function save(){formError.value='';if(!form.name.trim()){formError.value='请输入 Skill 名称。';return}const payload={name:form.name.trim(),version:form.version.trim(),description:form.description,category:form.category,project:form.category==='custom'?(form.project||null):null};for(const [key,label] of [['triggers','触发条件'],['capabilities','能力列表'],['tools','工具列表'],['knowledge','知识依赖'],['input_schema','输入定义'],['output_schema','输出定义']]){const value=json(form[key],label);if(value===null)return;payload[key]=value}busy.value=true;try{if(editing.value)await api.updateSkill(editing.value.id,payload);else await api.createSkill(payload);ElMessage.success('Skill 已保存');modal.value=false;await load()}catch(err){formError.value=explain(err,'保存失败，请检查内容后重试。')}finally{busy.value=false}}
async function toggle(item){busy.value=true;try{await api.toggleSkill(item.id);ElMessage.success('Skill 状态已更新');await load()}catch(err){ElMessage.error(explain(err,'状态更新失败，请重试。'))}finally{busy.value=false}}
async function remove(item){if(!window.confirm(`确认删除 Skill“${item.name}”？`))return;busy.value=true;try{await api.deleteSkill(item.id);ElMessage.success('Skill 已删除');await load()}catch(err){ElMessage.error(explain(err,'删除失败，请重试。'))}finally{busy.value=false}}
async function openExecute(item){const raw=window.prompt(`执行 Skill“${item.name}”，请输入 JSON：`,'{}');if(raw===null)return;executeTarget.value=item;executeInput.value=raw;await execute();if(executeError.value)ElMessage.error(executeError.value);else window.alert(`执行结果：\\n${executeResult.value}`)}
async function execute(){executeError.value='';executeResult.value='';let input;try{input=JSON.parse(executeInput.value)}catch{executeError.value='输入必须是有效 JSON。';return}executing.value=true;try{const result=await api.executeSkill(executeTarget.value.id,input);executeResult.value=JSON.stringify(result,null,2);ElMessage.success('Skill 执行完成')}catch(err){executeError.value=explain(err,'Skill 执行失败，请检查输入或运行时配置。')}finally{executing.value=false}}
function findChainExampleSkill(projectId){const candidates=skills.value.filter(item=>item.status==='enabled'&&(!item.project||String(item.project)===String(projectId||'')));return candidates.find(item=>item.category==='core')||candidates[0]||null}
function starterChainDefinition(skill){if(!skill)return{nodes:[]};return{nodes:[{node_id:'primary_skill',node_type:'skill',role:'core',skill_id:String(skill.id),skill_version_range:'*',execution_mode:'sequential',input_schema:{type:'object'},output_schema:{type:'object'},human_gate:'none',failure_strategy:'stop',depends_on:[],timeout_seconds:30,max_retries:0},{node_id:'human_review',node_type:'human_gate',role:'related',skill_id:null,skill_version_range:'*',execution_mode:'sequential',input_schema:{type:'object'},output_schema:{type:'object'},human_gate:'required',failure_strategy:'stop',depends_on:['primary_skill'],timeout_seconds:30,max_retries:0}],merge_strategy:'required_only',max_calls:20,max_runtime_seconds:300,max_cost_units:0,allowed_data_scopes:[]}}
function openChainForm(item=null){chainEditing.value=item;const projectId=item?.project||(canManageProject(project.value)?project.value:'')||manageableProjects.value[0]?.id||'';const exampleSkill=item?null:findChainExampleSkill(projectId);chainExampleSkill.value=exampleSkill?{id:String(exampleSkill.id),name:exampleSkill.name}:null;Object.assign(chainForm,{name:item?.name||'',version:item?.version||'1.0.0',description:item?.description||'',project:projectId,definition:JSON.stringify(item?.definition||starterChainDefinition(exampleSkill),null,2)});chainFormError.value='';chainModal.value=true}
async function deleteChain(item){if(!window.confirm(`确认删除 Skill 链“${item.name}”？`))return;chainBusy.value=true;try{await api.deleteSkillChain(item.id);ElMessage.success('Skill 链已删除');await load()}catch(err){ElMessage.error(explain(err,'Skill 链删除失败，请重试。'))}finally{chainBusy.value=false}}
async function saveChain(){chainFormError.value='';if(!chainForm.name.trim()){chainFormError.value='请输入 Skill 链名称。';return}let definition;try{definition=JSON.parse(chainForm.definition)}catch{chainFormError.value='链定义必须是有效 JSON。';return}if(!definition||typeof definition!=='object'||Array.isArray(definition)||!Array.isArray(definition.nodes)||!definition.nodes.length){chainFormError.value='链定义必须包含至少一个完整节点，不能只填写 Skill ID 列表。';return}const payload={name:chainForm.name.trim(),version:chainForm.version.trim(),description:chainForm.description,project:chainForm.project||null,definition};chainBusy.value=true;try{if(chainEditing.value)await api.updateSkillChain(chainEditing.value.id,payload);else await api.createSkillChain(payload);ElMessage.success('链路蓝图已保存为草稿；当前不会在业务流程中执行');chainModal.value=false;await load()}catch(err){chainFormError.value=explain(err,'Skill 链保存失败，请检查契约后重试。')}finally{chainBusy.value=false}}
async function refreshChains(){if(chainLoading.value)return;await load();if(!chainError.value)ElMessage.success('Skill 链契约已刷新')}function openConfigurationForm(item=null){configEditing.value=item;const selected=chains.value.find(chain=>String(chain.id)===String(item?.chain||''))||chains.value.find(chain=>chain.status==='enabled');Object.assign(configForm,{chain:item?.chain||selected?.id||'',layer:item?.layer||((project.value||projects.value.length)?'project':'global'),project:item?.project||(canManageProject(project.value)?project.value:'')||manageableProjects.value[0]?.id||'',feature_key:item?.feature_key||'requirement_analysis',version_lock:item?.version_lock||selected?.version||'',enabled:item?.enabled??true,max_calls:item?.overrides?.max_calls??'',max_runtime_seconds:item?.overrides?.max_runtime_seconds??'',max_cost_units:item?.overrides?.max_cost_units??'',allowed_data_scopes:(item?.overrides?.allowed_data_scopes||[]).join(', ')});configFormError.value='';configModal.value=true}
async function saveConfiguration(){configFormError.value='';if(!configForm.chain){configFormError.value='请选择链路名称。';return}if(configForm.layer!=='global'&&!configForm.project){configFormError.value='请选择项目范围。';return}if(configForm.layer==='feature'&&!configForm.feature_key){configFormError.value='请选择功能范围。';return}const overrides={...(configEditing.value?.overrides||{})};for(const key of ['max_calls','max_runtime_seconds','max_cost_units']){const raw=configForm[key];if(raw===''){delete overrides[key];continue}const value=Number(raw);if(!Number.isInteger(value)||value<0){configFormError.value='调用数、时长和费用上限必须是非负整数。';return}overrides[key]=value}if(configForm.allowed_data_scopes.trim())overrides.allowed_data_scopes=configForm.allowed_data_scopes.split(',').map(value=>value.trim()).filter(Boolean);else delete overrides.allowed_data_scopes;const payload={chain:configForm.chain,layer:configForm.layer,project:configForm.layer==='global'?null:configForm.project,feature_key:configForm.layer==='feature'?configForm.feature_key:'',request_key:'',version_lock:configForm.version_lock.trim(),overrides,enabled:configForm.enabled};configBusy.value=true;try{if(configEditing.value)await api.updateSkillChainConfiguration(configEditing.value.id,payload);else await api.createSkillChainConfiguration(payload);ElMessage.success('配置已保存并记录审计');configModal.value=false;previewResult.value=null;await load()}catch(err){configFormError.value=explain(err,'保存失败，请检查范围和权限后重试。')}finally{configBusy.value=false}}
async function toggleConfiguration(item){configBusy.value=true;try{await api.updateSkillChainConfiguration(item.id,{enabled:!item.enabled});ElMessage.success(item.enabled?'配置已停用':'配置已启用');await load()}catch(err){ElMessage.error(explain(err,'配置状态更新失败，请重试。'))}finally{configBusy.value=false}}
async function rollbackConfiguration(item){if(!window.confirm('回滚到该配置上一条审计版本？'))return;configBusy.value=true;try{await api.rollbackSkillChainConfiguration(item.id);ElMessage.success('配置已回滚');await load()}catch(err){ElMessage.error(explain(err,'没有可用的回滚版本，或当前账号无权限。'))}finally{configBusy.value=false}}
async function revokeConfiguration(item){if(!window.confirm('撤销此范围配置？系统会保留审计记录。'))return;configBusy.value=true;try{await api.deleteSkillChainConfiguration(item.id);ElMessage.success('配置已撤销，审计记录已保留');await load()}catch(err){ElMessage.error(explain(err,'配置撤销失败，请重试。'))}finally{configBusy.value=false}}
async function showConfigurationHistory(item){try{historyRows.value=await api.getSkillChainConfigurationHistory(item.id);historyModal.value=true}catch(err){ElMessage.error(explain(err,'审计记录加载失败，请重试。'))}}
async function previewEffectiveConfiguration(){previewLoading.value=true;previewResult.value=null;const payload={project:previewForm.project||null,feature_key:previewForm.feature_key||'',request_key:'',instant_chain:previewForm.instant_chain||''};try{previewResult.value=await api.resolveSkillChainConfiguration(payload)}catch(err){const body=err.response?.data||{};previewResult.value={...body,status:body.status||'failed',blocked:true,reason:body.reason||body.detail||explain(err,'配置预览失败，请重试。')}}finally{previewLoading.value=false}}
async function setChainEnabled(item){if(chainBusy.value)return;chainBusy.value=true;try{if(item.status==='enabled'){await api.pauseSkillChain(item.id);ElMessage.success('蓝图已暂停接收新运行；已启动运行不受影响')}else{let current=item;if(current.status==='draft'){current=await api.verifySkillChain(current.id)}if(current.status==='draft'||current.status==='verified'){current=await api.publishSkillChain(current.id)}await api.enableSkillChain(current.id);ElMessage.success('蓝图已启用，可供新运行选择')}await load()}catch(err){ElMessage.error(explain(err,'蓝图状态更新失败，请检查能力引用、版本状态和权限。'))}finally{chainBusy.value=false}}
function runStatusLabel(status){return({pending:'待执行',running:'运行中',pause_requested:'请求暂停',paused:'已暂停',waiting_human:'等待人工',completed:'已完成',failed:'失败',timed_out:'已超时',cancel_requested:'请求取消',cancelled:'已取消'})[status]||status}
async function startRun(item){const raw=window.prompt(`启动蓝图“${item.name}”，请输入运行输入 JSON：`,'{}');if(raw===null)return;let input;try{input=JSON.parse(raw)}catch{ElMessage.error('运行输入必须是有效 JSON。');return}runBusy.value=true;try{const result=await api.startSkillChainRun({chain_id:item.id,input,idempotency_key:`skills-${item.id}-${Date.now()}`});selectedRun.value=result;runDetailModal.value=true;ElMessage.success(result.status==='waiting_human'?'运行已到达人工确认点':'运行已创建');await loadRuns()}catch(err){ElMessage.error(explain(err,'运行启动失败，请检查蓝图状态、配置和权限。'))}finally{runBusy.value=false}}
async function showRun(item){runBusy.value=true;try{selectedRun.value=await api.getSkillChainRun(item.id);runDetailModal.value=true}catch(err){ElMessage.error(explain(err,'运行详情加载失败，请重试。'))}finally{runBusy.value=false}}
async function controlRun(action){if(!selectedRun.value)return;runBusy.value=true;try{let result;if(action==='pause')result=await api.pauseSkillChainRun(selectedRun.value.id);if(action==='cancel')result=await api.cancelSkillChainRun(selectedRun.value.id);if(action==='resume'){let input={};if(selectedRun.value.status==='waiting_human'){const raw=window.prompt('请输入人工确认结果 JSON：','{}');if(raw===null)return;input=JSON.parse(raw)}result=await api.resumeSkillChainRun(selectedRun.value.id,input)}selectedRun.value=result;await loadRuns();ElMessage.success(action==='pause'?'已请求在安全检查点暂停':action==='resume'?'已请求恢复运行':'已请求取消运行')}catch(err){ElMessage.error(explain(err,'运行控制失败，请刷新后重试。'))}finally{runBusy.value=false}}
async function forkChain(item){if(chainBusy.value)return;chainBusy.value=true;try{const draft=await api.forkSkillChainDraft(item.id);await load();openChainForm(draft);ElMessage.success('已创建新的草稿版本；原版本保持不变')}catch(err){ElMessage.error(explain(err,'新草稿创建失败，请重试。'))}finally{chainBusy.value=false}}
async function archiveChain(item){if(!window.confirm('归档此蓝图版本？归档会阻止新运行选择，并保留版本与审计记录。'))return;chainBusy.value=true;try{await api.archiveSkillChain(item.id);ElMessage.success('蓝图版本已归档');await load()}catch(err){ElMessage.error(explain(err,'蓝图归档失败，请先暂停启用中的版本。'))}finally{chainBusy.value=false}}
async function showChainVersions(item){selectedBlueprint.value=item;versionRows.value=[];diffResult.value=null;versionsError.value='';versionsModal.value=true;versionsLoading.value=true;try{versionRows.value=await api.listSkillChainVersions(item.id)}catch(err){versionsError.value=explain(err,'蓝图版本加载失败，请重试。')}finally{versionsLoading.value=false}}
function canRollbackTo(item){return Boolean(selectedBlueprint.value&&item.id!==selectedBlueprint.value.id&&item.published_at&&Date.parse(item.published_at)<Date.parse(selectedBlueprint.value.created_at))}
async function compareChainVersion(item){if(!selectedBlueprint.value)return;try{diffResult.value=await api.getSkillChainDiff(selectedBlueprint.value.id,item.id)}catch(err){ElMessage.error(explain(err,'蓝图差异加载失败，请重试。'))}}
async function rollbackChainVersion(item){if(!selectedBlueprint.value||!canRollbackTo(item))return;const current=selectedBlueprint.value;if(!window.confirm('将从 '+item.version+' 的已发布内容创建一个新的草稿版本，不覆盖任何历史版本。继续？'))return;chainBusy.value=true;try{const draft=await api.rollbackSkillChainVersion(current.id,item.id);ElMessage.success('已创建 '+draft.version+' 草稿；校验、发布并启用前不会用于新运行');versionsModal.value=false;await load()}catch(err){ElMessage.error(explain(err,'蓝图回滚未执行；历史内容保持不变。'))}finally{chainBusy.value=false}}
async function showChainHistory(item){selectedBlueprint.value=item;chainHistoryRows.value=[];chainHistoryError.value='';chainHistoryModal.value=true;chainHistoryLoading.value=true;try{chainHistoryRows.value=await api.getSkillChainHistory(item.id)}catch(err){chainHistoryError.value=explain(err,'蓝图审计历史加载失败，请检查读取权限后重试。')}finally{chainHistoryLoading.value=false}}
onMounted(load)
</script>
<template>
<WorkspaceShell active="skills">
  <div class="workspace-content model-page skills-page">
    <div class="page-title-row">
      <div>
        <p class="workspace-eyebrow">SKILL WORKBENCH</p>
        <h1>能力库与链路蓝图</h1>
        <p class="workspace-lead">先维护可复用的单项能力，再把能力组织成有顺序、有输入输出约定的工作流程。</p>
      </div>
      <button class="primary-action" @click="openForm()">＋ 新建单项能力</button>
    </div>

    <section class="skills-intro-grid" aria-label="能力库使用说明">
      <article>
        <p class="workspace-eyebrow">单项能力 · Skill</p>
        <h2>一个 Skill 做一类具体工作</h2>
        <p>例如“需求分析”负责识别功能点，“用例评审”负责检查覆盖和风险。编辑能力只修改这一项的说明、触发条件和输入输出，不会改动链路。</p>
      </article>
      <article>
        <p class="workspace-eyebrow">链路蓝图 · Skill Chain</p>
        <h2>把多个步骤和人工确认规则写成契约</h2>
        <p>例如“核心 Skill 处理 → 人工确认”。契约描述节点、先后依赖、数据格式和失败策略；它是工作流程蓝图，不是运行按钮。</p>
      </article>
    </section>

    <section class="skills-toolbar">
      <label>能力库项目筛选
        <select v-model="project" aria-label="能力库项目筛选">
          <option value="">全部可见能力</option>
          <option v-for="item in projects" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select>
      </label>
      <button type="button" class="text-action" :disabled="loading" @click.prevent="refreshSkills">{{ loading ? '加载中…' : '刷新能力与蓝图' }}</button>
    </section>

    <section class="skills-panel chain-contract-panel">
      <div class="chain-contract-header">
        <div>
          <p class="workspace-eyebrow">第二步 · 组合步骤</p>
          <h2>链路蓝图（Skill 链契约）</h2>
          <p class="skills-hint">描述流程由哪些节点组成、节点间如何传递数据、何时需要人工确认以及失败时如何处理。</p>
        </div>
        <div class="skills-actions">
          <button class="text-action" :disabled="chainLoading" @click.prevent="refreshChains">{{ chainLoading ? '加载中…' : '刷新契约' }}</button>
          <button v-if="isPlatformAdmin || manageableProjects.length > 0" class="primary-action" @click="openChainForm()">＋ 新建链路蓝图</button>
        </div>
      </div>
      <div class="skills-current-stage" role="note"><b>蓝图治理：</b>草稿先校验、再发布、再启用。暂停只阻止新运行选择，不暂停已启动运行；回滚会从明确选择的历史已发布版本创建新草稿。版本、配置与审计各自独立；需求分析和用例生成请从各自业务工作台进入。</div>
      <div v-if="chainLoading" class="state-panel" role="status"><span class="loading-ring"></span><b>正在加载 Skill 链契约</b></div>
      <div v-else-if="chainError" class="state-panel state-panel--error" role="alert"><b>暂时无法加载 Skill 链契约</b><p>{{ chainError }}</p><button type="button" @click.prevent="refreshChains">重试</button></div>
      <div v-else-if="!chains.length" class="skills-empty"><b>还没有链路蓝图</b><p>新建时会预填一条示例：一个现有核心 Skill，后接人工确认节点。创建会写入第一条蓝图审计；此时没有历史发布版本，回滚不可用。</p></div>
      <table v-else class="skills-table">
        <thead><tr><th>蓝图名称</th><th>范围</th><th>节点数</th><th>版本</th><th>生命周期</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in chains" :key="item.id">
            <td><b>{{ item.name }}</b><br><small>{{ item.description || '暂无说明' }}</small></td>
            <td>{{ item.project_name || '共享' }}</td>
            <td>{{ item.definition?.nodes?.length || 0 }} 个节点</td>
            <td>{{ item.schema_version }}</td>
            <td><span class="skills-chip" :class="{ off: item.status !== 'enabled' }">{{ item.status_label }}</span><small class="skills-status-help">{{ item.status === 'draft' ? '草稿：编辑后须校验和发布' : item.status === 'verified' ? '校验通过：发布后才能启用' : item.status === 'published' ? '已发布：尚未开放给新运行' : item.status === 'enabled' ? '允许新运行选择；暂停不影响已启动运行' : item.status === 'paused' ? '已暂停新运行，运行中任务不受影响' : item.status === 'archived' ? '已归档，不能用于新运行' : '旧版本状态，配置解析仍按版本启用状态校验' }}</small></td>
            <td><div class="skills-actions">
              <button v-if="canManageProject(item.project)" class="text-action" :disabled="chainBusy || item.status === 'archived'" @click="setChainEnabled(item)">{{ item.status === 'enabled' ? '暂停新运行' : '启动蓝图' }}</button>
              <button v-if="item.status === 'enabled'" class="text-action" :disabled="runBusy" @click="startRun(item)">调试运行</button>
              <button v-if="canManageProject(item.project) && item.status === 'draft'" class="text-action" @click="openChainForm(item)">编辑草稿</button>
              <button v-if="canManageProject(item.project) && item.status !== 'draft' && item.status !== 'archived'" class="text-action" :disabled="chainBusy" @click="forkChain(item)">编辑新版本</button>
              <button class="text-action" @click="showChainVersions(item)">版本与差异</button>
              <button v-if="canManageProject(item.project)" class="text-action" :disabled="chainBusy || !item.can_rollback" :title="item.can_rollback ? '选择一个更早的已发布版本并创建新草稿' : '暂无可回滚版本'" @click="showChainVersions(item)">{{ item.can_rollback ? '回滚版本' : '暂无可回滚版本' }}</button>
              <button v-if="canManageProject(item.project)" class="text-action" @click="showChainHistory(item)">蓝图审计</button>
              <button v-if="canManageProject(item.project) && item.status !== 'enabled' && item.status !== 'archived'" class="text-action" :disabled="chainBusy" @click="archiveChain(item)">归档</button>
              <button v-if="canManageProject(item.project) && item.status === 'draft' && !item.configuration_count" class="danger text-action" :disabled="chainBusy" @click="deleteChain(item)">删除草稿</button>
            </div></td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="skills-panel chain-run-panel">
      <div class="chain-contract-header">
        <div>
          <p class="workspace-eyebrow">第四步 · 运行与恢复</p>
          <h2>Skill 链运行工作台</h2>
          <p class="skills-hint">这里展示业务工作台产生的真实父运行和治理调试运行证据。运行会冻结蓝图、配置、输入和能力版本快照；暂停、恢复、取消只作用于单次运行，不改变蓝图生命周期。</p>
        </div>
        <button class="text-action" :disabled="runLoading" @click.prevent="loadRuns">{{ runLoading ? '加载中…' : '刷新运行' }}</button>
      </div>
      <div v-if="runLoading" class="state-panel" role="status"><span class="loading-ring"></span><b>正在加载运行记录</b></div>
      <div v-else-if="runError" class="state-panel state-panel--error" role="alert"><b>暂时无法加载运行记录</b><p>{{ runError }}</p><button type="button" @click.prevent="loadRuns">重试</button></div>
      <div v-else-if="!runs.length" class="skills-empty"><b>暂无运行记录</b><p>请从需求分析或用例生成工作台发起业务操作；管理员也可以从蓝图的“调试运行”验证运行契约。</p></div>
      <table v-else class="skills-table">
        <thead><tr><th>运行</th><th>蓝图快照</th><th>状态</th><th>当前节点</th><th>检查点</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in runs" :key="item.id">
            <td><code>{{ item.id.slice(0,8) }}</code><br><small>{{ item.created_at }}</small></td>
            <td><b>{{ item.chain_name || '已删除蓝图' }}</b><br><small>v{{ item.chain_version || '未知' }}</small></td>
            <td><span class="skills-chip" :class="{ off: !['running','completed'].includes(item.status) }">{{ runStatusLabel(item.status) }}</span><small class="skills-status-help">{{ item.error_message || '持久化状态可用于刷新恢复' }}</small></td>
            <td>{{ item.current_node_id || '—' }}</td><td>{{ item.checkpoint_node_id || '—' }}</td>
            <td><div class="skills-actions"><button class="text-action" @click="showRun(item)">查看详情</button><button v-if="item.chain && ['enabled'].includes(chains.find(chain=>String(chain.id)===String(item.chain))?.status)" class="text-action" :disabled="runBusy" @click="startRun(chains.find(chain=>String(chain.id)===String(item.chain)))">再次运行</button></div></td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="skills-panel chain-config-panel">
      <div class="chain-contract-header">
        <div>
          <p class="workspace-eyebrow">第三步 · 确定生效范围</p>
          <h2>Skill 链配置与解析预览</h2>
          <p class="skills-hint">配置按全局、项目、功能、即时指定逐层解析；同层冲突、停用或版本不兼容会明确阻断，不会静默降级。</p>
        </div>
        <button v-if="isPlatformAdmin || canManageProject(previewForm.project)" class="primary-action" @click="openConfigurationForm()">＋ 新建范围配置</button>
      </div>
      <div class="skills-current-stage" role="note"><b>状态边界：</b>启用表示链路配置可被解析；预览不是执行。“运行就绪”需要受控适配器和环境预检，当前尚未提供。安装记录也不等同于运行就绪。</div>
      <div class="config-preview-controls">
        <label>项目
          <select v-model="previewForm.project">
            <option value="">共享范围</option>
            <option v-for="item in projects" :key="item.id" :value="item.id">{{ item.name }}</option>
          </select>
        </label>
        <label>业务功能
          <select v-model="previewForm.feature_key">
            <option value="requirement_analysis">需求分析</option>
            <option value="requirement_review">需求评审</option>
            <option value="test_point_review">测试点评审</option>
            <option value="case_generation">用例生成</option>
            <option value="case_review">用例评审</option>
            <option value="manual_review">人工评审辅助</option>
          </select>
        </label>
        <label>本次即时选择
          <select v-model="previewForm.instant_chain">
            <option value="">沿用继承配置</option>
            <option v-for="item in chains" :key="item.id" :value="item.id">{{ item.name }} · v{{ item.version }}</option>
          </select>
        </label>
        <button class="primary-action" :disabled="previewLoading" @click.prevent="previewEffectiveConfiguration">{{ previewLoading ? '解析中…' : '解析当前配置' }}</button>
      </div>
      <div v-if="previewResult" class="config-preview-result" :class="{ 'config-preview-result--blocked': previewResult.blocked }" aria-live="polite">
        <b>{{ previewResult.status === 'resolved' ? '配置解析完成' : previewResult.status === 'unconfigured' ? '尚未配置' : '配置被阻断' }}</b>
        <p>{{ previewResult.reason }}</p>
        <p v-if="previewResult.chain">生效链路：{{ previewResult.chain.name }} · v{{ previewResult.chain.version }}；来源：{{ previewResult.source_label }}</p>
        <p v-if="previewResult.layers?.length">解析层级：{{ previewResult.layers.map(previewLayerLabel).join(' → ') }}</p>
        <p class="skills-hint">运行就绪：{{ previewResult.runtime_ready ? '是' : '否' }}。{{ previewResult.runtime_ready_reason }}</p>
        <p v-if="previewResult.issues?.length" class="skills-error">{{ previewResult.issues.map(issue => issue.message).join('；') }}</p>
      </div>
      <div v-if="configLoading" class="state-panel" role="status"><span class="loading-ring"></span>正在加载链路配置</div>
      <div v-else-if="configError" class="state-panel state-panel--error" role="alert"><p>{{ configError }}</p><button @click.prevent="load">重试</button></div>
      <div v-else-if="!configurations.length" class="skills-empty"><b>还没有范围配置</b><p>先启用一条 Skill 链，再按权限创建全局、项目或功能配置。</p></div>
      <table v-else class="skills-table">
        <thead><tr><th>生效链路</th><th>层级与范围</th><th>版本锁定</th><th>状态</th><th>审计</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in configurations" :key="item.id">
            <td><b>{{ item.chain_name }}</b></td>
            <td>{{ item.layer_label }} · {{ item.project_name || '共享' }}<small v-if="item.feature_key" class="skills-status-help">{{ item.feature_key }}</small></td>
            <td>{{ item.version_lock || '未锁定' }}</td>
            <td><span class="skills-chip" :class="{ off: !item.enabled }">{{ item.enabled ? '启用' : '停用' }}</span></td>
            <td>{{ item.audit_count }} 条</td>
            <td><div class="skills-actions">
              <button v-if="canManageConfiguration(item)" class="text-action" @click="openConfigurationForm(item)">编辑</button>
              <button v-if="canManageConfiguration(item)" class="text-action" @click="toggleConfiguration(item)">{{ item.enabled ? '停用' : '启用' }}</button>
              <button v-if="canManageConfiguration(item)" class="text-action" :disabled="!item.can_rollback" :title="item.can_rollback ? '恢复到上一条已记录的配置状态' : '暂无可回滚配置版本'" @click="rollbackConfiguration(item)">{{ item.can_rollback ? '回滚配置' : '暂无可回滚配置版本' }}</button>
              <button v-if="canManageConfiguration(item)" class="text-action" @click="showConfigurationHistory(item)">配置审计历史</button>
              <button v-if="canManageConfiguration(item)" class="danger text-action" @click="revokeConfiguration(item)">撤销</button>
            </div></td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="skills-panel">
      <header class="skills-section-heading">
        <div>
          <p class="workspace-eyebrow">单项能力库</p>
          <h2>一项 Skill = 一种可复用能力</h2>
          <p>下面的能力编号可用于契约中的 <code>skill_id</code>。“编辑能力”只改单项定义，“试运行”只单独运行此项。</p>
        </div>
      </header>
      <div v-if="loading" class="state-panel" role="status"><span class="loading-ring"></span><b>正在加载 Skills</b></div>
      <div v-else-if="error" class="state-panel state-panel--error" role="alert"><b>暂时无法加载</b><p>{{ error }}</p><button type="button" @click.prevent="refreshSkills">重试</button></div>
      <div v-else-if="!visibleSkills.length" class="skills-empty"><b>暂无可见单项能力</b><p>可创建项目级能力，或联系平台管理员启用共享能力。</p></div>
      <table v-else class="skills-table">
        <thead><tr><th>名称</th><th>分类</th><th>范围</th><th>状态</th><th>版本</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in visibleSkills" :key="item.id">
            <td><b>{{ item.name }}</b><br><small>{{ item.description || '暂无说明' }}</small><small class="skills-id">编号：{{ item.id }}</small></td>
            <td>{{ item.category_label }}</td><td>{{ item.project_name || '共享' }}</td>
            <td><span class="skills-chip" :class="{ off: item.status !== 'enabled' }">{{ item.status_label }}</span></td>
            <td>v{{ item.version }}</td>
            <td><div class="skills-actions">
              <button class="text-action" v-if="item.status === 'enabled'" title="只单独试运行这项能力，不会执行下方链路蓝图" @click="openExecute(item)">试运行</button>
              <button class="text-action" @click="toggle(item)">{{ item.status === 'enabled' ? '停用' : '启用' }}</button>
              <button class="text-action" title="编辑这项单独能力的说明、触发条件和输入输出" @click="openForm(item)">编辑能力</button>
              <button class="danger text-action" @click="remove(item)">删除</button>
            </div></td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>

  <Teleport to="body">
    <div v-if="modal" class="modal-backdrop" @click.self="!busy && (modal=false)">
      <section class="config-modal skills-modal">
        <header><h2>{{ editing ? '编辑单项能力' : '新建单项能力' }}</h2><button :disabled="busy" @click="modal=false">×</button></header>
        <form @submit.prevent="save">
          <fieldset class="skills-form" :disabled="busy">
            <p class="skills-guide">单项 Skill 就像一个“岗位”：定义它擅长什么、何时使用、需要什么输入、会给出什么输出。这里的编辑只改这一项能力，不会修改或运行链路蓝图。</p>
            <label>名称<input v-model="form.name" required></label>
            <label>版本<input v-model="form.version" required></label>
            <label>分类<select v-model="form.category"><option value="custom">自定义（项目级）</option><option value="core">核心（共享）</option><option value="specialized">专业（共享）</option><option value="auxiliary">辅助（共享）</option></select></label>
            <label v-if="form.category==='custom'">所属项目<select v-model="form.project"><option value="">请选择项目</option><option v-for="item in projects" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
            <label>说明<textarea v-model="form.description" rows="2"></textarea></label>
            <label>触发条件 JSON<textarea v-model="form.triggers" rows="2"></textarea></label>
            <label>能力列表 JSON<textarea v-model="form.capabilities" rows="2"></textarea></label>
            <p class="skills-hint">能力、工具、知识依赖使用 JSON 数组；输入和输出定义使用 JSON 对象。</p>
            <label>工具列表 JSON<textarea v-model="form.tools" rows="2"></textarea></label>
            <label>知识依赖 JSON<textarea v-model="form.knowledge" rows="2"></textarea></label>
            <label>输入定义 JSON<textarea v-model="form.input_schema" rows="2"></textarea></label>
            <label>输出定义 JSON<textarea v-model="form.output_schema" rows="2"></textarea></label>
            <p v-if="formError" class="skills-error" role="alert">{{ formError }}</p>
          </fieldset>
          <footer><button type="button" class="secondary-action" :disabled="busy" @click="modal=false">取消</button><button type="submit" class="primary-action" :disabled="busy">{{ busy ? '保存中…' : '保存' }}</button></footer>
        </form>
      </section>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="chainModal" class="modal-backdrop" @click.self="!chainBusy && (chainModal=false)">
      <section class="config-modal skills-modal">
        <header><h2>{{ chainEditing ? '编辑链路蓝图' : '新建链路蓝图' }}</h2><button :disabled="chainBusy" @click="chainModal=false">×</button></header>
        <form @submit.prevent="saveChain">
          <fieldset class="skills-form" :disabled="chainBusy">
            <div class="skills-guide">
              <b>Skill 是单项能力；链路契约是组合步骤的蓝图。</b>
              <p>新建时示例 JSON 已填入一项现有能力和后续人工确认节点。可直接保存草稿，或按需要编辑步骤与依赖。</p>
              <p v-if="chainExampleSkill">示例能力：{{ chainExampleSkill.name }}（编号：<code>{{ chainExampleSkill.id }}</code>）。若改为其他项目范围，请确认此能力对该项目可见。</p>
              <p v-else class="skills-guide-warning">没有可用于示例的启用能力；请先启用/创建一项可见 Skill，再填写 <code>skill_id</code>。</p>
              <p class="skills-guide-warning">保存仅校验并保存草稿，不会在业务页面生效或实际运行；配置由 T168、执行由 T169 提供。</p>
            </div>
            <label>链路名称<input v-model="chainForm.name" required></label>
            <label>契约版本<input v-model="chainForm.version" required></label>
            <label>数据范围<select v-model="chainForm.project"><option v-if="isPlatformAdmin" value="">共享蓝图（仅平台管理员）</option><option v-for="item in manageableProjects" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
            <label>用途说明<textarea v-model="chainForm.description" rows="2"></textarea></label>
            <label>链路定义（完整 JSON）<small>示例已预填。只填写 Skill ID 列表不够；每个 Skill 节点都要有唯一 node_id 和输入/输出 Schema。</small><textarea v-model="chainForm.definition" rows="14" spellcheck="false"></textarea></label>
            <details class="skills-field-guide">
              <summary>字段怎么填？展开查看</summary>
              <ul>
                <li><code>nodes</code>：步骤清单；<code>node_id</code> 是节点唯一名称。</li>
                <li><code>node_type</code>：<code>skill</code> 是能力步骤；<code>human_gate</code> 是人工确认点；<code>merge</code> 用于汇总分支。</li>
                <li><code>role</code>：一条链必须且只能有一个 <code>core</code> 核心 Skill，其他 Skill 节点为 <code>related</code> 关联能力。</li>
                <li><code>skill_id</code>：引用能力库中的编号；非 Skill 节点填 <code>null</code>。</li>
                <li><code>depends_on</code>：填写前置节点的 <code>node_id</code>；第一步填 <code>[]</code>。</li>
                <li><code>input_schema</code>/<code>output_schema</code>：声明输入/输出 JSON 结构，简单对象可从 <code>{"type":"object"}</code> 开始。</li>
                <li><code>execution_mode</code>：<code>sequential</code> 顺序或 <code>parallel</code> 并行；<code>human_gate</code> 为 <code>required</code> 表示需要人工把关。</li>
                <li><code>failure_strategy</code>：<code>stop</code> 停止、<code>continue</code> 继续或 <code>retry</code> 重试。</li>
              </ul>
            </details>
            <p v-if="chainFormError" class="skills-error" role="alert">{{ chainFormError }}</p>
          </fieldset>
          <footer><button type="button" class="secondary-action" :disabled="chainBusy" @click="chainModal=false">取消</button><button type="submit" class="primary-action" :disabled="chainBusy">{{ chainBusy ? '保存中…' : '保存契约草稿' }}</button></footer>
        </form>
      </section>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="configModal" class="modal-backdrop" @click.self="!configBusy && (configModal=false)">
      <section class="config-modal skills-modal">
        <header><h2>{{ configEditing ? '编辑范围配置' : '新建范围配置' }}</h2><button :disabled="configBusy" @click="configModal=false">×</button></header>
        <form @submit.prevent="saveConfiguration">
          <fieldset class="skills-form" :disabled="configBusy">
            <div class="skills-guide"><b>按链路名称配置，无需填写 Skill 编号或原始 JSON。</b><p>项目/功能配置优先于全局默认；本页只解析配置，不启动 Skill。</p></div>
            <label>Skill 链名称<select v-model="configForm.chain" required><option value="">请选择链路</option><option v-for="item in chains" :key="item.id" :value="item.id">{{ item.name }} · v{{ item.version }} · {{ item.status_label }}</option></select></label>
            <label>配置层级<select v-model="configForm.layer"><option v-if="isPlatformAdmin" value="global">全局默认（仅平台管理员）</option><option value="project">项目级</option><option value="feature">功能级</option></select></label>
            <label v-if="configForm.layer!=='global'">项目<select v-model="configForm.project"><option value="">请选择项目</option><option v-for="item in manageableProjects" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
            <label v-if="configForm.layer==='feature'">业务功能<select v-model="configForm.feature_key"><option value="requirement_analysis">需求分析</option><option value="requirement_review">需求评审</option><option value="test_point_review">测试点评审</option><option value="case_generation">用例生成</option><option value="case_review">用例评审</option><option value="manual_review">人工评审辅助</option></select></label>
            <label>锁定链版本（留空表示不锁定）<input v-model="configForm.version_lock" placeholder="例如 1.0.0"></label>
            <details class="skills-field-guide">
              <summary>可选覆盖字段</summary>
              <label>最大调用数<input v-model="configForm.max_calls" type="number" min="0"></label>
              <label>最大运行秒数<input v-model="configForm.max_runtime_seconds" type="number" min="0"></label>
              <label>最大费用单位<input v-model="configForm.max_cost_units" type="number" min="0"></label>
              <label>允许的数据范围（逗号分隔）<input v-model="configForm.allowed_data_scopes"></label>
              <small>空字段继承低层配置；填写的字段仅覆盖对应值。</small>
            </details>
            <p v-if="configFormError" class="skills-error" role="alert">{{ configFormError }}</p>
          </fieldset>
          <footer><button type="button" class="secondary-action" :disabled="configBusy" @click="configModal=false">取消</button><button type="submit" class="primary-action" :disabled="configBusy">{{ configBusy ? '保存中…' : '保存配置' }}</button></footer>
        </form>
      </section>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="versionsModal" class="modal-backdrop" @click.self="!chainBusy && (versionsModal=false)">
      <section class="config-modal skills-modal blueprint-history-modal">
        <header><h2>蓝图版本与差异 · {{ selectedBlueprint?.name }}</h2><button :disabled="chainBusy" @click="versionsModal=false">×</button></header>
        <div class="skills-form">
          <p class="skills-guide-warning">回滚会把明确选择的更早已发布版本复制为新草稿，不覆盖当前或历史版本。新草稿仍须校验、发布和启用。</p>
          <div v-if="versionsLoading" class="state-panel" role="status"><span class="loading-ring"></span>正在读取蓝图版本</div>
          <div v-else-if="versionsError" class="state-panel state-panel--error" role="alert"><p>{{ versionsError }}</p><button type="button" @click="showChainVersions(selectedBlueprint)">重试</button></div>
          <div v-else-if="!versionRows.length" class="skills-empty"><b>没有可见的版本记录</b><p>请刷新工作台，或确认当前账号有该项目的读取权限。</p></div>
          <div v-else>
            <article v-for="item in versionRows" :key="item.id" class="skills-guide">
              <b>{{ item.name }} · v{{ item.version }} · {{ item.status_label }}</b>
              <p>创建：{{ item.created_at }}<span v-if="item.published_at"> · 发布：{{ item.published_at }}</span></p>
              <div class="skills-actions">
                <button class="text-action" :disabled="item.id === selectedBlueprint?.id" @click="compareChainVersion(item)">与当前版本比较</button>
                <button v-if="canManageProject(selectedBlueprint?.project) && canRollbackTo(item)" class="text-action" :disabled="chainBusy" @click="rollbackChainVersion(item)">回滚到此版本（生成新草稿）</button>
              </div>
            </article>
            <p v-if="!selectedBlueprint?.can_rollback" class="skills-hint">暂无可回滚版本：当前蓝图之前没有已发布版本。</p>
          </div>
          <section v-if="diffResult" class="config-preview-result" aria-live="polite">
            <b>版本差异：v{{ diffResult.from_version }} → v{{ diffResult.to_version }}</b>
            <p>说明变化：{{ diffResult.description_changed ? '是' : '否' }}；契约格式变化：{{ diffResult.schema_version_changed ? '是' : '否' }}；旧 Skill 引用变化：{{ diffResult.legacy_skill_ids_changed ? '是' : '否' }}</p>
            <p>定义字段变化：{{ diffResult.definition_fields_changed?.length ? diffResult.definition_fields_changed.join('、') : '无' }}</p>
            <p>节点变化：{{ diffResult.node_changes?.length ? diffResult.node_changes.map(change => change.node_id + '（' + change.change + '）').join('、') : '无' }}</p>
            <small>差异视图只显示变化位置，不回显定义中的原始内容。</small>
          </section>
        </div>
        <footer><button class="secondary-action" :disabled="chainBusy" @click="versionsModal=false">关闭</button></footer>
      </section>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="chainHistoryModal" class="modal-backdrop" @click.self="chainHistoryModal=false">
      <section class="config-modal skills-modal blueprint-history-modal">
        <header><h2>蓝图审计历史</h2><button @click="chainHistoryModal=false">×</button></header>
        <div class="skills-form">
          <div v-if="chainHistoryLoading" class="state-panel" role="status"><span class="loading-ring"></span>正在读取蓝图审计记录</div>
          <div v-else-if="chainHistoryError" class="state-panel state-panel--error" role="alert"><p>{{ chainHistoryError }}</p><button type="button" @click="showChainHistory(selectedBlueprint)">重试</button></div>
          <div v-else-if="!chainHistoryRows.length" class="skills-empty"><b>暂无蓝图审计记录</b><p>历史旧版本没有审计身份时会明确显示“操作者未知”。</p></div>
          <article v-for="item in chainHistoryRows" :key="item.id" class="skills-guide">
            <b>{{ auditActionLabel(item.action) }} · {{ item.actor_display_name || item.actor_username || '历史记录 / 操作者未知' }}</b>
            <p>{{ item.created_at }} · {{ auditRoleLabel(item.actor_role) }} · 操作者编号：{{ item.actor_id || '未知' }}</p>
            <small>授权范围：{{ item.actor_scope?.scope_type === 'project' ? '项目 ' + (item.actor_scope?.project_name || item.actor_scope?.project_id) : item.actor_scope?.scope_type === 'global' ? '全局' : '历史范围未知' }} · 结果：{{ item.result || '历史结果未知' }}</small>
            <p>版本：{{ item.before_state?.version || '初次创建' }} → {{ item.after_state?.version || '未知' }}<span v-if="item.after_state?.details?.restored_version"> · 回滚来源 v{{ item.after_state.details.restored_version }}</span></p>
            <p>{{ item.reason || '未填写操作说明' }}</p>
          </article>
        </div>
        <footer><button class="secondary-action" @click="chainHistoryModal=false">关闭</button></footer>
      </section>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="historyModal" class="modal-backdrop" @click.self="historyModal=false">
      <section class="config-modal skills-modal">
        <header><h2>范围配置审计历史</h2><button @click="historyModal=false">×</button></header>
        <div class="skills-form">
          <div v-for="item in historyRows" :key="item.id" class="skills-guide">
            <b>{{ auditActionLabel(item.action) }} · {{ item.actor_display_name || item.actor_username || '历史记录 / 操作者未知' }}</b>
            <p>{{ item.created_at }} · {{ auditRoleLabel(item.actor_role) }} · {{ item.reason || '配置状态已记录' }}</p>
            <small>授权范围：{{ item.actor_scope?.scope_type === 'project' ? '项目 ' + (item.actor_scope?.project_name || item.actor_scope?.project_id) : item.actor_scope?.scope_type === 'global' ? '全局' : '历史范围未知' }} · 结果：{{ item.result || '历史结果未知' }} · {{ item.after_state?.layer }} / {{ item.after_state?.enabled ? '启用' : '停用' }} / {{ item.after_state?.version_lock || '未锁定' }}</small>
          </div>
          <p v-if="!historyRows.length" class="skills-hint">暂无审计记录</p>
        </div>
        <footer><button class="secondary-action" @click="historyModal=false">关闭</button></footer>
      </section>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="runDetailModal && selectedRun" class="modal-backdrop" @click.self="!runBusy && (runDetailModal=false)">
      <section class="config-modal skills-modal blueprint-history-modal">
        <header><h2>运行详情 · {{ selectedRun.id.slice(0,8) }}</h2><button :disabled="runBusy" @click="runDetailModal=false">×</button></header>
        <div class="skills-form">
          <p class="skills-guide"><b>{{ selectedRun.chain_name || '已删除蓝图' }} · v{{ selectedRun.chain_version || '未知' }}</b><br>状态：{{ runStatusLabel(selectedRun.status) }} · 当前节点：{{ selectedRun.current_node_id || '无' }} · 安全检查点：{{ selectedRun.checkpoint_node_id || '无' }}</p>
          <p v-if="selectedRun.error_message" class="skills-error" role="alert">{{ selectedRun.error_code }}：{{ selectedRun.error_message }}</p>
          <div class="skills-actions">
            <button v-if="['pending','running','pause_requested'].includes(selectedRun.status)" class="text-action" :disabled="runBusy" @click="controlRun('pause')">安全暂停</button>
            <button v-if="['paused','waiting_human'].includes(selectedRun.status)" class="text-action" :disabled="runBusy" @click="controlRun('resume')">恢复运行</button>
            <button v-if="!['completed','failed','timed_out','cancelled'].includes(selectedRun.status)" class="danger text-action" :disabled="runBusy" @click="controlRun('cancel')">取消运行</button>
          </div>
          <article v-for="node in selectedRun.nodes||[]" :key="node.id" class="skills-guide">
            <b>{{ node.position+1 }}. {{ node.node_id }} · {{ node.status }}</b>
            <p>类型：{{ node.node_type }} · 尝试：{{ node.attempt }} · 检查点：{{ node.checkpoint_safe ? '是' : '否' }}</p>
            <small v-if="node.error_message">{{ node.error_code }}：{{ node.error_message }}</small>
          </article>
          <details class="skills-field-guide"><summary>查看冻结快照摘要</summary><pre>{{ JSON.stringify(selectedRun.execution_snapshot,null,2) }}</pre></details>
        </div>
        <footer><button class="secondary-action" :disabled="runBusy" @click="runDetailModal=false">关闭</button></footer>
      </section>
    </div>
  </Teleport>
</WorkspaceShell>
</template>
