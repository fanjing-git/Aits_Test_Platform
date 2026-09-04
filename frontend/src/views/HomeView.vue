<script setup>
import { onMounted } from 'vue'
import { getServiceHealth } from '../api/health'
import { useAppStore } from '../stores/app'

const appStore = useAppStore()

onMounted(async () => {
  try {
    const result = await getServiceHealth()
    appStore.setServiceStatus(result.status === 'ok' ? 'ok' : 'unavailable')
  } catch {
    appStore.setServiceStatus('unavailable')
  }
})
</script>

<template>
  <main class="welcome-page">
    <section class="welcome-card">
      <p class="welcome-card__eyebrow">AI AGENT TEST PLATFORM</p>
      <h1>AI 智能体测试平台</h1>
      <p class="welcome-card__description">前端工程已就绪，后续功能将按照任务依赖逐步接入。</p>
      <el-tag :type="appStore.isHealthy ? 'success' : 'info'" effect="light" round>
        后端服务：{{ appStore.serviceStatus }}
      </el-tag>
    </section>
  </main>
</template>
