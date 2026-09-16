const STAGE_LABELS = {
  invalid_url: '地址校验',
  unsafe_target: '目标安全校验',
  dns_failed: 'DNS 解析',
  tcp_blocked: 'TCP 网络连接',
  provider_timeout: '模型响应超时',
  tls_failed: 'TLS 安全连接',
  proxy_unavailable: '代理连接',
  auth_failed: '供应商鉴权',
  quota_exhausted: '额度或限流',
  model_capability_mismatch: '模型能力',
  provider_http_error: '供应商接口',
  local_network_blocked: '本机网络策略',
  network_error: '网络连接',
}

const SUGGESTIONS = {
  invalid_url: '请检查 API 基础地址，只填写供应商要求的 HTTPS 基础地址。',
  unsafe_target: '请使用已登记的供应商域名和 HTTPS 443 端口，不要填写 IP、内网或本机地址。',
  dns_failed: '请检查服务器 DNS、供应商地域地址和网络出口。',
  tcp_blocked: '请让管理员放行后端进程访问供应商 TCP 443，或为 Django/Celery 配置代理。',
  provider_timeout: '模型响应时间超过当前配置，请稍后重试或提高结构化调用超时配置。',
  tls_failed: '请检查服务器时间、CA 证书、TLS 配置和代理证书链。',
  proxy_unavailable: '请检查后端和 Celery Worker 的代理地址、认证信息和 CA 证书。',
  auth_failed: '请检查 API Key、地域、业务空间和模型授权。',
  quota_exhausted: '请检查供应商账户额度、限流和计费状态。',
  model_capability_mismatch: '请确认模型名称与所选能力类型匹配。',
  provider_http_error: '请根据供应商返回的 HTTP 状态检查接口地址、协议和模型名称。',
}

export function connectionStageLabel(code) {
  return STAGE_LABELS[code] || '供应商连接'
}

export function connectionFailure(error, fallback = '连接测试失败，请检查地址、凭据和服务器网络后重试。') {
  const data = error?.response?.data || error?.data || error || {}
  const code = typeof data.code === 'string' ? data.code : ''
  const message = typeof data.message === 'string'
    ? data.message
    : typeof data.detail === 'string' ? data.detail : fallback
  return {
    ok: false,
    code,
    stage: code ? connectionStageLabel(code) : '供应商连接',
    message,
    suggestion: SUGGESTIONS[code] || '请检查服务器网络、代理、凭据和供应商配置后重试。',
  }
}
