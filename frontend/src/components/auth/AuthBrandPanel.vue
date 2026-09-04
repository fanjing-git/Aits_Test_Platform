<script setup>
defineProps({
  eyebrow: { type: String, default: 'AUTONOMOUS QUALITY ENGINEERING' },
})
</script>

<template>
  <section class="auth-brand">
    <div class="auth-brand__mesh"></div>
    <div class="cosmic-orbit cosmic-orbit--one"></div>
    <div class="cosmic-orbit cosmic-orbit--two"></div>
    <div class="cosmic-core" aria-hidden="true"><span></span></div>
    <div class="auth-brand__content">
      <div class="brand-mark" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>
      <p class="auth-brand__eyebrow">{{ eyebrow }}</p>
      <h1>让每一次测试<br><em>更智能，更确定</em></h1>
      <p class="auth-brand__intro">
        从需求理解、用例生成到执行分析，让 AI 智能体成为你的持续质量伙伴。
      </p>
      <div class="auth-brand__signals" aria-label="平台核心能力">
        <div><strong>10+</strong><span>测试场景智能编排</span></div>
        <div><strong>全链路</strong><span>可追踪质量闭环</span></div>
        <div><strong>7×24</strong><span>持续质量洞察</span></div>
      </div>
    </div>
    <div class="auth-brand__status"><i></i> AI ENGINE ONLINE</div>
  </section>
</template>
