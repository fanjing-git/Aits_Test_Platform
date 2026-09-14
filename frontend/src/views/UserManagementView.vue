<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import { createPasswordResetLink, inviteUser, listAccountAuditEvents, listUsers, resendUserInvitation, revokeUserActions, updateUser } from '../api/users'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'
import { useUserStore } from '../stores/user'

const roleOptions = [
  ['admin', '管理员'],
  ['test_leader', '测试负责人'],
  ['tester', '测试工程师'],
  ['developer', '开发工程师'],
  ['viewer', '访客'],
]
const roleDescriptions = {
  admin: '平台配置、用户授权与全部业务操作',
  test_leader: '测试规划、执行、环境与质量管理',
  tester: '用例设计、测试执行与报告查看',
  developer: '负责模块的执行与报告查看',
  viewer: '只读查看已授权报告',
}

const userStore = useUserStore()
const router = useRouter()
const users = ref([])
const loading = ref(true)
const loadError = ref('')
const editingUser = ref(null)
const saving = ref(false)
const formError = ref('')
const form = reactive({ role: 'viewer', is_active: true })
const inviteOpen = ref(false)
const inviteSaving = ref(false)
const inviteError = ref('')
const inviteForm = reactive({ account: '', role: 'viewer', expires_in_hours: 72 })
const actionResult = ref(null)
const currentOrigin = window.location.origin
const auditEvents = ref([])
const auditError = ref('')

const activeCount = computed(() => users.value.filter((user) => user.is_active).length)
const adminCount = computed(() => users.value.filter((user) => user.role === 'admin').length)

function apiError(error, fallback) {
  const data = error.response?.data
  if (typeof data?.detail === 'string') return data.detail
  if (data && typeof data === 'object') {
    const first = Object.entries(data)[0]
    if (first) return `${first[0]}：${Array.isArray(first[1]) ? first[1][0] : first[1]}`
  }
  return fallback
}

async function loadUsers() {
  loading.value = true
  loadError.value = ''
  try {
    users.value = await listUsers()
  } catch (error) {
    loadError.value = apiError(error, '用户列表加载失败，请确认服务状态后重试。')
  } finally {
    loading.value = false
  }
  try {
    auditError.value = ''
    auditEvents.value = await listAccountAuditEvents()
  } catch (error) {
    auditError.value = apiError(error, '审计记录暂时无法加载。')
  }
}

function openEdit(user) {
  editingUser.value = user
  form.role = user.role
  form.is_active = user.is_active
  formError.value = ''
}

function openInvite() {
  inviteForm.account = ''
  inviteForm.role = 'viewer'
  inviteForm.expires_in_hours = 72
  inviteError.value = ''
  inviteOpen.value = true
}

async function submitInvite() {
  if (!inviteForm.account.trim()) {
    inviteError.value = '请输入同事的用户名或邮箱。'
    return
  }
  inviteSaving.value = true
  inviteError.value = ''
  try {
    const result = await inviteUser({ ...inviteForm, account: inviteForm.account.trim() })
    inviteOpen.value = false
    actionResult.value = { title: '邀请链接已生成', label: '一次性激活链接', path: result.activation_path, expires_at: result.expires_at, username: result.user.username }
    await loadUsers()
  } catch (error) {
    inviteError.value = apiError(error, '邀请失败，请检查账号是否重复或服务状态。')
  } finally {
    inviteSaving.value = false
  }
}

async function runAccountAction(user, action, successTitle) {
  try {
    const result = await action(user.id)
    const path = result.activation_path || result.reset_path
    actionResult.value = { title: successTitle, label: result.activation_path ? '一次性激活链接' : '一次性密码重置链接', path, expires_at: result.expires_at, username: user.username }
    await loadUsers()
  } catch (error) {
    ElMessage.error(apiError(error, '操作失败，请刷新后重试。'))
  }
}

async function revokeActions(user) {
  try {
    await revokeUserActions(user.id)
    ElMessage.success(`已撤销“${user.username}”的未使用链接`)
    await loadUsers()
  } catch (error) {
    ElMessage.error(apiError(error, '撤销失败，请刷新后重试。'))
  }
}

async function copyActionLink() {
  if (!actionResult.value?.path) return
  const link = `${window.location.origin}${actionResult.value.path}`
  try {
    await navigator.clipboard.writeText(link)
  } catch {
    const input = document.createElement('textarea')
    input.value = link
    document.body.appendChild(input)
    input.select()
    document.execCommand('copy')
    input.remove()
  }
  ElMessage.success('链接已复制，可发送给同事')
}

async function saveUser() {
  if (!editingUser.value) return
  saving.value = true
  formError.value = ''
  try {
    await updateUser(editingUser.value.id, {
      role: form.role,
      is_active: form.is_active,
    })
    ElMessage.success(`“${editingUser.value.username}”的权限已更新`)
    const changedCurrentUser = editingUser.value.id === userStore.user?.id
    editingUser.value = null
    if (changedCurrentUser) {
      await userStore.hydrate()
      if (userStore.user?.role !== 'admin') {
        await router.push('/workspace')
        return
      }
    }
    await loadUsers()
  } catch (error) {
    formError.value = apiError(error, '保存失败，请检查当前账号和角色设置。')
  } finally {
    saving.value = false
  }
}

function displayDate(value, userId) {
  if (!value && userId === userStore.user?.id) return '当前会话在线'
  if (!value) return '尚未登录'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

onMounted(loadUsers)
</script>

<template>
  <WorkspaceShell active="users">
    <div class="workspace-content model-page user-page">
      <div class="page-title-row">
        <div>
          <p class="workspace-eyebrow">IDENTITY & ACCESS CONTROL</p>
          <h1>用户与权限</h1>
          <p class="workspace-lead">集中查看平台成员，并按照职责安全分配操作权限。</p>
        </div>
        <div class="page-actions"><button class="primary-action" @click="openInvite">邀请同事</button><button class="secondary-action" @click="loadUsers">刷新数据</button></div>
      </div>

      <section class="model-summary" aria-label="用户概览">
        <article><small>平台用户</small><strong>{{ users.length }}</strong><span>个已注册账号</span></article>
        <article><small>当前启用</small><strong>{{ activeCount }}</strong><span>可正常登录平台</span></article>
        <article><small>平台管理员</small><strong>{{ adminCount }}</strong><span>拥有全局管理权限</span></article>
      </section>

      <section class="model-panel">
        <div class="panel-heading"><div><h2>成员权限列表</h2><p>邀请会创建一个待激活账号；同事设置自己的密码后，再由管理员加入具体项目。</p></div></div>
        <div v-if="loading" class="state-panel"><span class="loading-ring"></span><b>正在同步成员信息</b><p>请稍候，平台正在读取最新账号和角色状态。</p></div>
        <div v-else-if="loadError" class="state-panel state-panel--error"><b>暂时无法加载</b><p>{{ loadError }}</p><button @click="loadUsers">重新加载</button></div>
        <div v-else-if="!users.length" class="state-panel"><b>还没有平台用户</b><p>用户完成注册后会显示在这里。</p></div>
        <div v-else class="model-table-wrap">
          <table class="model-table user-table">
            <thead><tr><th>用户</th><th>当前角色</th><th>账号状态</th><th>最近登录</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="user in users" :key="user.id">
                <td><div class="identity-cell"><span>{{ user.username.slice(0, 1).toUpperCase() }}</span><div><b>{{ user.username }}</b><small>{{ user.email || '未绑定邮箱' }}</small></div></div></td>
                <td><span :class="['role-chip', `role-chip--${user.role}`]">{{ user.role_label }}</span><small class="role-note">{{ roleDescriptions[user.role] }}</small></td>
                <td><span :class="['status-chip', user.is_active ? 'is-online' : 'is-offline']"><i></i>{{ user.is_active ? '正常' : '已停用' }}</span></td>
                <td>{{ displayDate(user.last_login, user.id) }}</td>
                <td><div class="row-actions"><button @click="openEdit(user)">{{ user.id === userStore.user?.id ? '查看本人' : '调整权限' }}</button><button v-if="!user.is_active" @click="runAccountAction(user, resendUserInvitation, '激活链接已重新生成')">重发邀请</button><button v-if="user.is_active" @click="runAccountAction(user, createPasswordResetLink, '密码重置链接已生成')">重置密码</button><button v-if="user.pending_invitation || user.pending_password_reset" class="danger-link" @click="revokeActions(user)">撤销链接</button></div></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="model-panel account-audit-panel">
        <div class="panel-heading"><div><h2>账号授权审计</h2><p>记录邀请、激活、角色调整、停用和密码链接操作；不保存明文密码或一次性令牌。</p></div></div>
        <div v-if="auditError" class="state-panel state-panel--error"><p>{{ auditError }}</p><button @click="loadUsers">重新加载</button></div>
        <div v-else-if="!auditEvents.length" class="state-panel"><b>暂无账号审计记录</b><p>完成一次邀请或权限调整后，系统会在这里保留安全操作证据。</p></div>
        <div v-else class="model-table-wrap"><table class="model-table user-table"><thead><tr><th>时间</th><th>事件</th><th>目标账号</th><th>操作人</th><th>安全摘要</th></tr></thead><tbody><tr v-for="event in auditEvents" :key="event.id"><td>{{ displayDate(event.created_at) }}</td><td><span class="role-chip">{{ event.event_label }}</span></td><td>{{ event.target_username }}</td><td>{{ event.actor_username || '同事本人' }}</td><td>{{ Object.keys(event.metadata || {}).join('、') || '无附加字段' }}</td></tr></tbody></table></div>
      </section>
    </div>

    <div v-if="inviteOpen" class="modal-backdrop" @click.self="inviteOpen = false">
      <section class="config-modal user-modal" role="dialog" aria-modal="true" aria-labelledby="invite-form-title">
        <header><div><small>ACCOUNT ONBOARDING</small><h2 id="invite-form-title">邀请同事加入平台</h2></div><button aria-label="关闭" @click="inviteOpen = false">×</button></header>
        <div class="config-form">
          <label><span>用户名或邮箱</span><input v-model="inviteForm.account" autocomplete="off" placeholder="例如：zhangsan 或 name@example.com" @keyup.enter="submitInvite"><small>系统会创建待激活账号，不设置临时密码；同事通过一次性链接自行设置密码。</small></label>
          <label><span>平台角色</span><select v-model="inviteForm.role"><option v-for="option in roleOptions" :key="option[0]" :value="option[0]">{{ option[1] }} · {{ roleDescriptions[option[0]] }}</option></select><small>默认建议使用访客或测试工程师，管理员权限应单独审批。</small></label>
          <label><span>链接有效期</span><select v-model.number="inviteForm.expires_in_hours"><option :value="24">24 小时</option><option :value="72">72 小时</option><option :value="168">7 天</option></select></label>
          <p v-if="inviteError" class="form-error" role="alert">{{ inviteError }}</p>
        </div>
        <footer><button class="secondary-action" @click="inviteOpen = false">取消</button><button class="primary-action" :disabled="inviteSaving" @click="submitInvite">{{ inviteSaving ? '生成中…' : '生成邀请链接' }}</button></footer>
      </section>
    </div>

    <div v-if="actionResult" class="modal-backdrop" @click.self="actionResult = null">
      <section class="config-modal user-modal" role="dialog" aria-modal="true" aria-labelledby="action-result-title">
        <header><div><small>ONE-TIME SECURITY LINK</small><h2 id="action-result-title">{{ actionResult.title }}</h2></div><button aria-label="关闭" @click="actionResult = null">×</button></header>
        <div class="config-form action-result-form"><p>目标账号：<b>{{ actionResult.username }}</b></p><p>链接仅显示在本次操作中，请立即复制并通过安全渠道发送给同事。系统不会保存明文链接。</p><textarea readonly :value="`${currentOrigin}${actionResult.path}`" rows="3"></textarea><small>有效期至：{{ displayDate(actionResult.expires_at) }}</small></div>
        <footer><button class="secondary-action" @click="actionResult = null">关闭</button><button class="primary-action" @click="copyActionLink">复制链接</button></footer>
      </section>
    </div>

    <div v-if="editingUser" class="modal-backdrop" @click.self="editingUser = null">
      <section class="config-modal user-modal" role="dialog" aria-modal="true" aria-labelledby="user-form-title">
        <header><div><small>ACCESS POLICY</small><h2 id="user-form-title">调整用户权限</h2></div><button aria-label="关闭" @click="editingUser = null">×</button></header>
        <div class="config-form">
          <div class="selected-user"><span>{{ editingUser.username.slice(0, 1).toUpperCase() }}</span><div><b>{{ editingUser.username }}</b><small>{{ editingUser.email || '未绑定邮箱' }}</small></div></div>
          <label><span>平台角色</span><select v-model="form.role"><option v-for="option in roleOptions" :key="option[0]" :value="option[0]">{{ option[1] }} · {{ roleDescriptions[option[0]] }}</option></select><small v-if="editingUser.id === userStore.user?.id">可以调整自己的角色，但系统必须保留至少一名启用中的管理员；角色变更后页面权限会立即更新。</small></label>
          <div class="account-switch"><div><b>允许登录</b><small>停用后该账号将无法重新登录平台</small></div><label class="switch"><input v-model="form.is_active" type="checkbox" :disabled="editingUser.id === userStore.user?.id"><span></span></label></div>
          <p v-if="formError" class="form-error">{{ formError }}</p>
        </div>
        <footer><button class="secondary-action" @click="editingUser = null">取消</button><button class="primary-action" :disabled="saving" @click="saveUser">{{ saving ? '正在保存…' : '保存权限' }}</button></footer>
      </section>
    </div>
  </WorkspaceShell>
</template>
