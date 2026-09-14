import test from 'node:test'
import assert from 'node:assert/strict'

import { connectionFailure, connectionStageLabel } from '../src/utils/modelConnection.js'

test('maps blocked backend calls to a concrete stage and recovery suggestion', () => {
  const result = connectionFailure({ response: { data: {
    code: 'tcp_blocked',
    message: '本机网络策略拒绝了 Django/Python 的外网连接。',
  } } })
  assert.equal(result.stage, 'TCP 网络连接')
  assert.match(result.suggestion, /放行后端进程/)
  assert.equal(result.ok, false)
})

test('does not expose unknown provider errors as an empty message', () => {
  const result = connectionFailure({ response: { data: { code: 'unknown_stage' } } })
  assert.equal(result.stage, '供应商连接')
  assert.match(result.message, /连接测试失败/)
  assert.match(result.suggestion, /服务器网络/)
})

test('keeps stable labels for security and authentication failures', () => {
  assert.equal(connectionStageLabel('unsafe_target'), '目标安全校验')
  assert.equal(connectionStageLabel('auth_failed'), '供应商鉴权')
})
