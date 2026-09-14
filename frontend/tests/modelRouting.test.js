import test from 'node:test'
import assert from 'node:assert/strict'

import { capabilityContractLabel, routeSourceLabel, routingPayload } from '../src/utils/modelRouting.js'

test('route source labels are understandable Chinese text', () => {
  assert.equal(routeSourceLabel('global'), '平台全局默认')
  assert.equal(routeSourceLabel('feature'), '功能绑定')
  assert.equal(routeSourceLabel('unknown'), 'unknown')
  assert.equal(routeSourceLabel(''), '未配置')
})

test('routing payload preserves inherit-global and policy switches', () => {
  assert.deepEqual(routingPayload({
    feature_key: 'case_generation',
    primary_model_id: 0,
    backup_model_id: 12,
    allow_fallback: true,
    allow_deterministic_baseline: false,
  }), {
    feature_key: 'case_generation',
    primary_model_id: null,
    backup_model_id: 12,
    allow_fallback: true,
    allow_deterministic_baseline: false,
    is_active: true,
  })
})

test('capability contract gives the operator a real input/output contract', () => {
  assert.equal(
    capabilityContractLabel({ label: '需求深度分析', input_mode: 'text', output_mode: 'json_object' }),
    '需求深度分析：文本输入 → 结构化 JSON',
  )
  assert.equal(capabilityContractLabel(null), '未声明调用契约')
})
