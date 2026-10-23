// 假后端：GET /api/v1/history
//
// 形状照 app/routers/history.py 和 app/history/store.py 抄：
//
//   · 返回的是**裸数组**，不是 { items: [...] }
//   · 一行 = 一次检索，不是一次请求。翻页不算新记录
//   · 身份是 (user_id, kind, query, filters)，同样的条件再搜一次只 UPDATE：
//     search_count + 1、last_page 取最大值、last_seen_at 刷新，不会堆行
//   · filters 是字典，键名和请求体一致（mode / time_weight / layout / publish_date_*）
//   · kind 只认 report 和 oirf，limit 是 1..100，越界 422 且 detail 是数组
//   · result_total 可能是 null（老记录没存结果数），页面要能显示成 “—”
//
// 数据只在内存里，vite 一重启就没了 —— 真后端是 Postgres 的 search_history 表。

import { tokenUser } from './dev-auth.js'

const KINDS = ['oirf', 'report']
const MAX_LIMIT = 100

// 这几项不算“筛选条件”，对应 store.py 里的 _NOT_FILTERS
const NOT_FILTERS = ['q', 'page', 'size', 'highlight']

const rows = new Map()
let nextId = 1

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function send(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(body))
}

// 条件是个对象，键顺序不同会拼出不同的键，所以排一下序再拼
function keyOf(userId, kind, query, filters) {
  const parts = Object.keys(filters)
    .sort()
    .map((key) => `${key}=${JSON.stringify(filters[key])}`)
  return [userId, kind, query, parts.join('&')].join('|')
}

// 对应 store.py 的 split_request：请求体拆成“检索词”和“筛选条件”
function filtersOf(body) {
  const filters = {}
  for (const [key, value] of Object.entries(body)) {
    if (NOT_FILTERS.includes(key)) continue
    if (value === undefined || value === null) continue
    filters[key] = value
  }

  // mode 和 time_weight 在 pydantic 里有默认值，客户端不传也会被填上，
  // 所以这两项永远在条件里 —— 页面上照实显示就行
  if (filters.mode === undefined) filters.mode = 'or'
  if (filters.time_weight === undefined) filters.time_weight = 0
  return filters
}

// owner 是我们自己加的，真后端不返回这个字段，别漏给前端
function viewOf(row) {
  const copy = { ...row }
  delete copy.owner
  return copy
}

// 检索成功后被 dev-reports.js 调用，就是真后端那个 background task
export function recordSearch(user, body, resultTotal) {
  const kind = 'report'
  const query = body.q ?? ''
  const page = body.page ?? 1
  const size = body.size ?? 20
  const filters = filtersOf(body)
  const key = keyOf(user.id, kind, query, filters)
  const now = new Date().toISOString()

  const row = rows.get(key)
  if (row) {
    row.last_page = Math.max(row.last_page, page)
    row.size = size
    row.result_total = resultTotal
    row.search_count += 1
    row.last_seen_at = now
    return
  }

  rows.set(key, {
    id: nextId++,
    owner: user.id,
    kind,
    query,
    filters,
    last_page: page,
    size,
    result_total: resultTotal,
    search_count: 1,
    first_seen_at: now,
    last_seen_at: now,
  })
}

function handleHistory(user, params) {
  const kind = params.get('kind')
  const limitText = params.get('limit')
  // FastAPI 的 Query 默认值：不传就是 20
  const limit = limitText === null ? 20 : Number(limitText)

  const errors = []
  if (kind !== null && !KINDS.includes(kind)) {
    errors.push({
      loc: ['query', 'kind'],
      msg: "Input should be 'oirf' or 'report'",
      type: 'literal_error',
    })
  }
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) {
    errors.push({
      loc: ['query', 'limit'],
      msg: 'Input should be between 1 and 100',
      type: 'less_than_equal',
    })
  }
  if (errors.length) return { status: 422, body: { detail: errors } }

  const list = [...rows.values()]
    .filter((row) => row.owner === user.id)
    .filter((row) => !kind || row.kind === kind)
    .sort((a, b) => b.last_seen_at.localeCompare(a.last_seen_at))
    .slice(0, limit)
    .map(viewOf)

  return { status: 200, body: list }
}

// 种子数据：真后端里这些是之前搜过的记录，这里先塞几条，
// 免得第一次打开是一片空白，看不出表格长什么样。
function seedRows() {
  const now = Date.now()
  const seeds = [
    {
      query: '工业机器人 应用场景',
      filters: { mode: 'or', time_weight: 0.3, layout: '横版', publish_date_from: '2023-01-01' },
      last_page: 1,
      size: 20,
      result_total: 3,
      search_count: 4,
      minutesAgo: 42,
    },
    {
      query: '3D工业相机',
      filters: { mode: 'and', time_weight: 0 },
      last_page: 2,
      size: 20,
      result_total: 12,
      search_count: 1,
      minutesAgo: 26 * 60,
    },
    {
      query: '氢能产业园',
      filters: { mode: 'phrase', time_weight: 0 },
      last_page: 1,
      size: 20,
      // 故意留一条 null：真表里老记录没有结果数，页面得显示得出来
      result_total: null,
      search_count: 2,
      minutesAgo: 51 * 60,
    },
  ]

  for (const seed of seeds) {
    const at = new Date(now - seed.minutesAgo * 60 * 1000).toISOString()
    rows.set(keyOf(1, 'report', seed.query, seed.filters), {
      id: nextId++,
      owner: 1,
      kind: 'report',
      query: seed.query,
      filters: seed.filters,
      last_page: seed.last_page,
      size: seed.size,
      result_total: seed.result_total,
      search_count: seed.search_count,
      first_seen_at: at,
      last_seen_at: at,
    })
  }
}

seedRows()

export default function devHistoryMock() {
  return {
    name: 'dev-history-mock',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url, 'http://localhost')
        if (req.method !== 'GET' || url.pathname !== '/api/v1/history') return next()

        // 真后端查 Postgres，这里也慢一点，方便看加载态
        await delay(200)

        const user = tokenUser(req)
        if (!user) return send(res, 401, { detail: 'Not authenticated' })

        const out = handleHistory(user, url.searchParams)
        return send(res, out.status, out.body)
      })

      server.config.logger.info(
        '  history mock 已启用：GET /api/v1/history（边搜边攒，重启清空）',
      )
    },
  }
}
