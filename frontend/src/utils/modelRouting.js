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
