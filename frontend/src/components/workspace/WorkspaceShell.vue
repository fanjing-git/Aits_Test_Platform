<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { useUserStore } from '../../stores/user'

defineProps({
  active: { type: String, default: 'workspace' },
})

const router = useRouter()
const userStore = useUserStore()
const isAdmin = computed(() => userStore.user?.role === 'admin')

async function logout() {
  userStore.logout()
  await router.push('/login')
}
</script>

<template>
  <main class="workspace-shell">
    <div class="workspace-aurora workspace-aurora--one"></div>
    <div class="workspace-aurora workspace-aurora--two"></div>
    <aside class="workspace-sidebar">
      <div class="workspace-logo"><span class="brand-dot"></span><b>AITS</b></div>
      <nav>
        <RouterLink to="/workspace" :class="{ 'is-active': active === 'workspace' }"><i>⌂</i><span>工作台</span></RouterLink>
        <RouterLink to="/workspace/projects" :class="{ 'is-active': active === 'projects' }"><i>◇</i><span>项目与智能体</span><small>LIVE</small></RouterLink>
        <RouterLink to="/workspace/environments" :class="{ 'is-active': active === 'environments' }"><i>◎</i><span>环境管理</span><small>LIVE</small></RouterLink>
        <RouterLink to="/workspace/knowledge" :class="{ 'is-active': active === 'knowledge' }"><i>▤</i><span>知识库</span><small>LIVE</small></RouterLink>
        <RouterLink to="/workspace/requirements" :class="{ 'is-active': active === 'requirements' }"><i>⌁</i><span>需求分析</span><small>LIVE</small></RouterLink>
        <RouterLink to="/workspace/case-generation" :class="{ 'is-active': active === 'case-generation' }"><i>▣</i><span>用例生成</span><small>LIVE</small></RouterLink>
        <RouterLink to="/workspace/skills" :class="{ 'is-active': active === 'skills' }"><i>✧</i><span>Skills</span><small>LIVE</small></RouterLink>
        <a><i>✦</i><span>智能体</span><small>待开发</small></a>
        <a><i>⌘</i><span>测试任务</span><small>待开发</small></a>
        <a><i>▱</i><span>质量报告</span><small>待开发</small></a>
        <RouterLink v-if="isAdmin" to="/workspace/models" :class="{ 'is-active': active === 'models' }"><i>⚙</i><span>模型配置</span><small>ADMIN</small></RouterLink>
        <RouterLink v-if="isAdmin" to="/workspace/prompts" :class="{ 'is-active': active === 'prompts' }"><i>⌁</i><span>提示词配置</span><small>ADMIN</small></RouterLink>
        <RouterLink v-if="isAdmin" to="/workspace/users" :class="{ 'is-active': active === 'users' }"><i>♙</i><span>用户权限</span><small>ADMIN</small></RouterLink>
        <RouterLink v-if="isAdmin" to="/workspace/skill-audits" :class="{ 'is-active': active === 'skill-audits' }"><i>!</i><span>Skill audits</span><small>ADMIN</small></RouterLink>
        <RouterLink v-if="isAdmin" to="/workspace/skill-installations" :class="{ 'is-active': active === 'skill-installations' }"><i>+</i><span>Skill installations</span><small>ADMIN</small></RouterLink>
      </nav>
      <button class="sidebar-logout" @click="logout">退出登录</button>
    </aside>
    <section class="workspace-main">
      <header class="workspace-header">
        <div class="system-cluster"><span class="system-status"><i></i> SYSTEM ONLINE</span><small>SHANGHAI · NODE 01</small></div>
        <div class="user-chip">
          <span>{{ userStore.user?.username?.slice(0, 1)?.toUpperCase() }}</span>
          <div><b>{{ userStore.user?.username }}</b><small>{{ userStore.user?.role || 'viewer' }}</small></div>
        </div>
      </header>
      <slot />
    </section>
  </main>
</template>
