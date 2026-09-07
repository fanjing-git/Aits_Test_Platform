/** Fetch every catalogue page without accepting stale or looping responses. */
export async function loadAllModelPages(fetchPage, payload, onPage, isCurrent = () => true) {
  const found = new Map()
  const seen = new Set()
  let cursor = ''
  do {
    const page = await fetchPage({ ...payload, cursor })
    if (!isCurrent()) return
    if (!Array.isArray(page.models)) throw new Error('供应商模型目录格式不正确。')
    for (const model of page.models) {
      if (typeof model.id !== 'string' || !Array.isArray(model.types)) throw new Error('供应商模型条目格式不正确。')
      found.set(model.id, model)
    }
    cursor = page.next_cursor || ''
    if (cursor && seen.has(cursor)) throw new Error('供应商分页重复，目录未完整加载。')
    seen.add(cursor)
    onPage([...found.values()], Boolean(cursor))
  } while (cursor && isCurrent())
}

/** Resolve both listed models and custom deployment names using one rule. */
export function resolveModelName(selection, customName) {
  return (selection === '__custom__' ? customName : selection).trim()
}
