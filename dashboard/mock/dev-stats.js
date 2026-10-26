import { mockReports } from '../src/mock/data.js'
import { tokenUser } from './dev-auth.js'

const MAX_DAYS = 90
const MAX_INDUSTRIES = 10
const MAX_TOP_QUERIES = 5
const SEED_USER_ID = 1

const events = []
const KINDS = ['oirf', 'report']

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function send(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(body))
}

function pad(n) {
  return String(n).padStart(2, '0')
}

function dateKey(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function dayStart(offset) {
  const date = new Date()
  date.setHours(0, 0, 0, 0)
  date.setDate(date.getDate() - offset)
  return date
}

function latencyOf(query, offset) {
  return 45 + ((query.length * 13 + offset * 7) % 150)
}

function seedEvents() {
  const seeds = [
    [13, 9, '工业机器人 应用场景', 3],
    [13, 15, '3D工业相机', 12],
    [12, 10, '氢能产业园', 7],
    [11, 9, '人形机器人 供应链', 6],
    [11, 14, '固态电池 量产', 4],
    [11, 16, '钙钛矿 组件', 0],
    [9, 10, '储能 出货量', 5],
    [9, 11, '工业软件 国产替代', 8],
    [8, 15, '低空经济', 2],
    [6, 9, '工业机器人 应用场景', 3],
    [6, 17, '3D工业相机', 12],
    [5, 10, '氢能产业园', 7],
    [4, 9, '人形机器人 供应链', 6],
    [4, 13, '固态电池 量产', 4],
    [3, 10, '工业机器人 应用场景', 3],
    [2, 9, '3D工业相机', 12],
    [2, 15, '钙钛矿 组件', 0],
    [1, 10, '储能 出货量', 5],
  ]

  for (const [offset, hour, query, total] of seeds) {
    const at = dayStart(offset)
    at.setHours(hour, 15, 0, 0)
    events.push({
      userId: SEED_USER_ID,
      kind: 'report',
      query,
      total,
      ok: true,
      latencyMs: latencyOf(query, offset),
      date: dateKey(at),
    })
  }

  const failedAt = dayStart(4)
  failedAt.setHours(16, 40, 0, 0)
  events.push({
    userId: SEED_USER_ID,
    kind: 'report',
    query: '工业软件 国产替代',
    total: null,
    ok: false,
    latencyMs: 0,
    date: dateKey(failedAt),
  })
}

seedEvents()

export function recordSearchEvent({ userId, kind = 'report', query, page = 1, total, latencyMs = 0 }) {
  if (page !== 1) return
  if (typeof query !== 'string' || !query.trim()) return

  events.push({
    userId,
    kind,
    query: query.trim(),
    total: typeof total === 'number' ? total : null,
    ok: true,
    latencyMs,
    date: dateKey(new Date()),
  })
}

function reportStats() {
  const total = mockReports.length

  const yearCounts = new Map()
  for (const report of mockReports) {
    const year = Number(report.publish_date.slice(0, 4))
    yearCounts.set(year, (yearCounts.get(year) ?? 0) + 1)
  }

  const firstYear = Math.min(...yearCounts.keys())
  const lastYear = Math.max(...yearCounts.keys())
  const years = []
  for (let year = firstYear; year <= lastYear; year += 1) {
    years.push({ year, count: yearCounts.get(year) ?? 0 })
  }

  const industryCounts = new Map()
  for (const report of mockReports) {
    for (const name of report.industry) {
      industryCounts.set(name, (industryCounts.get(name) ?? 0) + 1)
    }
  }

  const industries = [...industryCounts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh'))
    .slice(0, MAX_INDUSTRIES)

  const layoutCounts = new Map()
  for (const report of mockReports) {
    layoutCounts.set(report.layout, (layoutCounts.get(report.layout) ?? 0) + 1)
  }

  const layouts = [...layoutCounts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh'))

  const dates = mockReports.map((report) => report.publish_date).sort()

  return {
    total,
    years,
    industries,
    industry_count: industryCounts.size,
    layouts,
    publish_range: { from: dates[0], to: dates[dates.length - 1] },
    generated_at: new Date().toISOString(),
  }
}

function searchStats(user, days, scope, kind) {
  const daily = []
  const byDate = new Map()

  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const key = dateKey(dayStart(offset))
    const row = { date: key, searches: 0, zero_result: 0, errors: 0 }
    daily.push(row)
    byDate.set(key, row)
  }

  const hits = events.filter((event) => {
    if (kind && event.kind !== kind) return false
    if (scope === 'me' && event.userId !== user.id) return false
    return byDate.has(event.date)
  })

  const queryCounts = new Map()
  let zeroResult = 0
  let errors = 0
  let latencySum = 0
  let latencyCount = 0

  for (const event of hits) {
    const row = byDate.get(event.date)
    row.searches += 1

    if (!event.ok) {
      row.errors += 1
      errors += 1
      continue
    }

    if (event.total === 0) {
      row.zero_result += 1
      zeroResult += 1
    }

    latencySum += event.latencyMs
    latencyCount += 1
    queryCounts.set(event.query, (queryCounts.get(event.query) ?? 0) + 1)
  }

  const topQueries = [...queryCounts.entries()]
    .map(([query, count]) => ({ query, count }))
    .sort((a, b) => b.count - a.count || a.query.localeCompare(b.query, 'zh'))
    .slice(0, MAX_TOP_QUERIES)

  return {
    days,
    daily,
    top_queries: topQueries,
    totals: {
      searches: hits.length,
      zero_result_rate: hits.length ? Number((zeroResult / hits.length).toFixed(4)) : 0,
      avg_latency_ms: latencyCount ? Math.round(latencySum / latencyCount) : 0,
    },
  }
}

function parseSearchParams(params) {
  const dayText = params.get('days')
  const scope = params.get('scope') ?? 'all'
  const kind = params.get('kind')
  const days = dayText === null ? 14 : Number(dayText)
  const errors = []

  if (!Number.isInteger(days) || days < 1 || days > MAX_DAYS) {
    errors.push({
      loc: ['query', 'days'],
      msg: `Input should be between 1 and ${MAX_DAYS}`,
      type: 'less_than_equal',
    })
  }

  if (scope !== 'all' && scope !== 'me') {
    errors.push({
      loc: ['query', 'scope'],
      msg: "Input should be 'all' or 'me'",
      type: 'literal_error',
    })
  }

  if (kind !== null && !KINDS.includes(kind)) {
    errors.push({
      loc: ['query', 'kind'],
      msg: "Input should be 'oirf' or 'report'",
      type: 'literal_error',
    })
  }

  return { days, scope, kind, errors }
}

export default function devStatsMock() {
  return {
    name: 'dev-stats-mock',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url, 'http://localhost')
        if (req.method !== 'GET') return next()

        const isReports = url.pathname === '/api/v1/stats/reports'
        const isSearch = url.pathname === '/api/v1/stats/search'
        if (!isReports && !isSearch) return next()

        await delay(180)

        const user = tokenUser(req)
        if (!user) return send(res, 401, { detail: 'Not authenticated' })

        if (isReports) return send(res, 200, reportStats())

        const parsed = parseSearchParams(url.searchParams)
        if (parsed.errors.length) return send(res, 422, { detail: parsed.errors })

        return send(res, 200, searchStats(user, parsed.days, parsed.scope, parsed.kind))
      })

      server.config.logger.info(
        '  stats mock 已启用：GET /api/v1/stats/reports、GET /api/v1/stats/search（只算 page = 1）',
      )
    },
  }
}
