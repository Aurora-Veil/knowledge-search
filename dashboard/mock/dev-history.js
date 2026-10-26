import { tokenUser } from './dev-auth.js'

const KINDS = ['oirf', 'report']
const MAX_LIMIT = 100

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

function keyOf(userId, kind, query, filters) {
  const parts = Object.keys(filters)
    .sort()
    .map((key) => `${key}=${JSON.stringify(filters[key])}`)
  return [userId, kind, query, parts.join('&')].join('|')
}

function filtersOf(body) {
  const filters = {}
  for (const [key, value] of Object.entries(body)) {
    if (NOT_FILTERS.includes(key)) continue
    if (value === undefined || value === null) continue
    filters[key] = value
  }

  if (filters.mode === undefined) filters.mode = 'or'
  if (filters.time_weight === undefined) filters.time_weight = 0
  return filters
}

function viewOf(row) {
  const copy = { ...row }
  delete copy.owner
  return copy
}

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
    if (page === 1) row.search_count += 1
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
      result_total: null,
      search_count: 2,
      minutesAgo: 51 * 60,
    },
    {
      query: '人形机器人 减速器',
      filters: { mode: 'or', time_weight: 0 },
      last_page: 1,
      size: 20,
      result_total: 4,
      search_count: 1,
      minutesAgo: 3 * 24 * 60,
    },
    {
      query: '储能 出货量',
      filters: { mode: 'and', layout: '横版' },
      last_page: 1,
      size: 20,
      result_total: 5,
      search_count: 2,
      minutesAgo: 5 * 24 * 60,
    },
    {
      query: '低空经济 eVTOL',
      filters: { mode: 'phrase', publish_date_from: '2024-01-01' },
      last_page: 2,
      size: 20,
      result_total: 2,
      search_count: 1,
      minutesAgo: 8 * 24 * 60,
    },
    {
      query: '钙钛矿 组件',
      filters: { mode: 'or', layout: '竖版' },
      last_page: 1,
      size: 20,
      result_total: 0,
      search_count: 1,
      minutesAgo: 12 * 24 * 60,
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
