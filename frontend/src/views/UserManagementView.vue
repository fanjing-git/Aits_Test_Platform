<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import { listUsers, updateUser } from '../api/users'
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
}

function openEdit(user) {
  editingUser.value = user
  form.role = user.role
  form.is_active = user.is_active
  formError.value = ''
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
        <button class="secondary-action" @click="loadUsers">刷新数据</button>
      </div>

      <section class="model-summary" aria-label="用户概览">
        <article><small>平台用户</small><strong>{{ users.length }}</strong><span>个已注册账号</span></article>
        <article><small>当前启用</small><strong>{{ activeCount }}</strong><span>可正常登录平台</span></article>
        <article><small>平台管理员</small><strong>{{ adminCount }}</strong><span>拥有全局管理权限</span></article>
      </section>

      <section class="model-panel">
        <div class="panel-heading"><div><h2>成员权限列表</h2><p>新用户默认为访客；管理员可根据实际职责调整角色。</p></div></div>
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
                <td><div class="row-actions"><button @click="openEdit(user)">{{ user.id === userStore.user?.id ? '查看本人' : '调整权限' }}</button></div></td>
              </tr>
            </tbody>
          </table>
        </div>
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
