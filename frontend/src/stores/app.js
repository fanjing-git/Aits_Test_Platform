import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', () => {
  const serviceStatus = ref('checking')
  const isHealthy = computed(() => serviceStatus.value === 'ok')

  function setServiceStatus(status) {
    serviceStatus.value = status
  }

  return { serviceStatus, isHealthy, setServiceStatus }
})
