<script setup>
import { onMounted } from 'vue'
import WorkspaceShell from '../components/workspace/WorkspaceShell.vue'
import { useUserStore } from '../stores/user'

const userStore = useUserStore()

onMounted(() => userStore.hydrate())

const modules = [
  ['需求智能分析', '解析需求文档，识别功能、流程与风险', '01'],
  ['测试用例生成', '多轮生成、评审与自动化筛选', '02'],
  ['智能测试执行', '接口、AI、性能与 APP 测试编排', '03'],
  ['质量洞察报告', '覆盖度、趋势与 ROI 分析', '04'],
]
</script>

<template>
  <WorkspaceShell active="workspace">
    <div class="workspace-content">
        <p class="workspace-eyebrow">AI QUALITY COMMAND CENTER</p>
        <h1>下午好，{{ userStore.user?.username }}</h1>
        <p class="workspace-lead">平台基础空间已就绪。后续能力将按照开发任务逐步接入。</p>
        <section class="command-card">
          <div class="command-card__glyph" aria-hidden="true">✦</div>
          <div><span>NEW TEST MISSION</span><h2>告诉智能体，你想测试什么？</h2><p>对话式测试入口将在智能体核心引擎完成后开放。</p></div>
          <button disabled>即将开放 <b>→</b></button>
        </section>
        <div class="module-grid">
          <article v-for="module in modules" :key="module[2]">
            <span>{{ module[2] }}</span><h3>{{ module[0] }}</h3><p>{{ module[1] }}</p><small>PLANNED</small>
          </article>
        </div>
    </div>
  </WorkspaceShell>
</template>
