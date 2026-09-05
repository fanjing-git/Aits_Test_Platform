import { createRouter, createWebHistory } from 'vue-router'
import { pinia } from '../stores'
import { useUserStore } from '../stores/user'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/workspace' },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { guestOnly: true },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('../views/RegisterView.vue'),
      meta: { guestOnly: true },
    },
    {
      path: '/workspace',
      name: 'workspace',
      component: () => import('../views/DashboardView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/workspace/models',
      name: 'model-configs',
      component: () => import('../views/ModelConfigView.vue'),
      meta: { requiresAuth: true, roles: ['admin'] },
    },
    {
      path: '/workspace/users',
      name: 'user-management',
      component: () => import('../views/UserManagementView.vue'),
      meta: { requiresAuth: true, roles: ['admin'] },
    },
    {
      path: '/workspace/prompts',
      name: 'prompt-configs',
      component: () => import('../views/PromptConfigView.vue'),
      meta: { requiresAuth: true, roles: ['admin'] },
    },
    {
      path: '/workspace/projects',
      name: 'project-agents',
      component: () => import('../views/ProjectAgentView.vue'),
      meta: { requiresAuth: true },
    },
    { path: '/workspace/environments', name: 'environments', component: () => import('../views/EnvironmentView.vue'), meta: { requiresAuth: true } },
    { path: '/workspace/knowledge', name: 'knowledge', component: () => import('../views/KnowledgeView.vue'), meta: { requiresAuth: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const userStore = useUserStore(pinia)
  if (userStore.isAuthenticated && !userStore.user) await userStore.hydrate()
  if (to.meta.requiresAuth && !userStore.isAuthenticated) return { name: 'login' }
  if (to.meta.roles && !to.meta.roles.includes(userStore.user?.role)) {
    return { name: 'workspace', query: { denied: to.name } }
  }
  if (to.meta.guestOnly && userStore.isAuthenticated) return { name: 'workspace' }
  return true
})

export default router
