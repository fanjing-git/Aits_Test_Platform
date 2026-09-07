import test from 'node:test'
import assert from 'node:assert/strict'

import { routeSourceLabel, routingPayload } from '../src/utils/modelRouting.js'

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
