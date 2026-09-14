export const routeSourceLabels = {
  operation: '本次操作临时选择',
  feature: '功能绑定',
  global: '平台全局默认',
  legacy_type_default: '历史按类型默认',
  backup: '备用模型',
}

export function routeSourceLabel(source) {
  return routeSourceLabels[source] || source || '未配置'
}

export function capabilityContractLabel(contract) {
  if (!contract) return '未声明调用契约'
  const inputLabels = {
    text: '文本输入',
    text_and_image: '文本 + 图片输入',
    text_and_tools: '文本 + 工具上下文',
    text_or_documents: '文本或文档输入',
    provider_metadata: '配置元数据',
  }
  const outputLabels = {
    json_object: '结构化 JSON',
    vectors_or_ranked_documents: '向量或排序结果',
    configuration: '配置结果',
  }
  return `${contract.label || '模型调用'}：${inputLabels[contract.input_mode] || contract.input_mode || '输入'} → ${outputLabels[contract.output_mode] || contract.output_mode || '结果'}`
}

export function routingPayload(row) {
  return {
    feature_key: row.feature_key,
    primary_model_id: row.primary_model_id || null,
    backup_model_id: row.backup_model_id || null,
    allow_fallback: Boolean(row.allow_fallback),
    allow_deterministic_baseline: Boolean(row.allow_deterministic_baseline),
    is_active: row.is_active !== false,
  }
}
