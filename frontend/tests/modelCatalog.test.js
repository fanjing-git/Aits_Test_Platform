import test from 'node:test'
import assert from 'node:assert/strict'
import { loadAllModelPages, resolveModelName } from '../src/utils/modelCatalog.js'

test('loads every page beyond a small recommendation list and deduplicates IDs', async () => {
  let output
  let calls = 0
  await loadAllModelPages(async ({ cursor }) => {
    const page = Number(cursor || 0)
    calls++
    return { models: Array.from({ length: 101 }, (_, i) => ({ id: `m-${page * 100 + i}`, types: ['other'] })), next_cursor: page < 14 ? String(page + 1) : '' }
  }, { provider: 'qwen' }, (items) => { output = items })
  assert.equal(calls, 15)
  assert.equal(output.length, 1501)
  assert.equal(output.at(-1).id, 'm-1500')
})

test('switching provider while a request is pending cannot overwrite the new selection', async () => {
  let current = true
  let resolve
  const pending = loadAllModelPages(() => new Promise((done) => { resolve = done }), {}, () => assert.fail('stale result published'), () => current)
  current = false
  resolve({ models: [{ id: 'old-provider-model', types: ['chat'] }], next_cursor: '2' })
  await pending
})

test('partial page failure is surfaced and not marked complete', async () => {
  const progress = []
  await assert.rejects(loadAllModelPages(async ({ cursor }) => {
    if (cursor) throw new Error('HTTP 503')
    return { models: [{ id: 'first', types: ['chat'] }], next_cursor: '2' }
  }, {}, (items, hasNext) => progress.push({ count: items.length, hasNext })), /503/)
  assert.deepEqual(progress, [{ count: 1, hasNext: true }])
})

test('looping pagination is rejected instead of hanging', async () => {
  await assert.rejects(loadAllModelPages(async () => ({ models: [], next_cursor: '2' }), {}, () => {}), /分页重复/)
})

test('empty account catalogue is a valid complete result', async () => {
  let output
  await loadAllModelPages(async () => ({ models: [], next_cursor: '' }), {}, (items, more) => { output = { items, more } })
  assert.deepEqual(output, { items: [], more: false })
})

test('custom deployments save their actual names rather than a UI sentinel', () => {
  assert.equal(resolveModelName('__custom__', ' deployment-east '), 'deployment-east')
  assert.equal(resolveModelName('__custom__', '  '), '')
  assert.equal(resolveModelName('qwen-model', ''), 'qwen-model')
})
