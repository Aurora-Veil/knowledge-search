import { mockReports } from '../src/mock/data.js'
import { tokenUser } from './dev-auth.js'

const MAX_SPAN_DAYS = 366
const MAX_INDUSTRIES = 10
const MAX_QUERIES = 20
const MAX_TOP_QUERIES = 20
const SEED_USER_ID = 1

const events = []
const KINDS = ['oirf', 'report']
const GRANULARITIES = ['day', 'week', 'month']

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

function addDays(date, days) {
  const next = new Date(date)
  next.setDate(next.getDate() + days)
  return next
}

function dateFromKey(key) {
  const [year, month, day] = key.split('-').map(Number)
  return new Date(year, month - 1, day)
}

function parseDateText(text) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return null
  const [year, month, day] = text.split('-').map(Number)
  const date = new Date(year, month - 1, day)
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    return null
  }
  return date
}

function bucketStart(date, granularity) {
  const start = new Date(date)
  start.setHours(0, 0, 0, 0)
  if (granularity === 'week') {
    const offset = (start.getDay() + 6) % 7
    start.setDate(start.getDate() - offset)
  } else if (granularity === 'month') {
    start.setDate(1)
  }
  return start
}

function nextBucket(date, granularity) {
  const next = new Date(date)
  if (granularity === 'week') next.setDate(next.getDate() + 7)
  else if (granularity === 'month') next.setMonth(next.getMonth() + 1)
  else next.setDate(next.getDate() + 1)
  return next
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

function searchStats({ days, start, end, queries, kind, granularity, limit }) {
  // 汇总表只到昨天，今天的数据不在范围内
  const dataUntil = dateKey(addDays(dayStart(0), -1))
  const rangeEnd = end ?? dayStart(0)
  const rangeStart = start ?? addDays(rangeEnd, -(days - 1))
  const startKey = dateKey(rangeStart)
  const endKey = dateKey(rangeEnd)
  const stopKey = endKey < dataUntil ? endKey : dataUntil
  const stop = dateFromKey(stopKey)

  const all = events.filter((event) => {
    if (event.date < startKey || event.date > stopKey) return false
    if (kind && event.kind !== kind) return false
    return true
  })

  const hits = queries.length
    ? all.filter((event) => queries.includes(event.query))
    : all

  const daily = []
  const byBucket = new Map()
  for (let cursor = bucketStart(rangeStart, granularity);
       cursor <= stop;
       cursor = nextBucket(cursor, granularity)) {
    const key = dateKey(cursor)
    const row = {
      date: key,
      searches: 0,
      zero_result: 0,
      errors: 0,
      latency_sum: 0,
      ok_count: 0,
    }
    daily.push(row)
    byBucket.set(key, row)
  }

  for (const event of hits) {
    const key = dateKey(bucketStart(dateFromKey(event.date), granularity))
    const row = byBucket.get(key)
    if (!row) continue

    row.searches += 1

    if (!event.ok) {
      row.errors += 1
      continue
    }

    if (event.total === 0) row.zero_result += 1

    row.latency_sum += event.latencyMs
    row.ok_count += 1
  }

  const queryCounts = new Map()
  for (const event of all) {
    queryCounts.set(event.query, (queryCounts.get(event.query) ?? 0) + 1)
  }

  const topQueries = [...queryCounts.entries()]
    .map(([query, count]) => ({ query, count }))
    .sort((a, b) => b.count - a.count || a.query.localeCompare(b.query, 'zh'))
    .slice(0, limit)

  const sum = (field) => daily.reduce((total, row) => total + row[field], 0)
  const searches = sum('searches')
  const zeroResult = sum('zero_result')
  const errors = sum('errors')
  const latencySum = sum('latency_sum')
  const okCount = sum('ok_count')

  return {
    range: { start: startKey, end: endKey, granularity },
    data_until: dataUntil,
    daily,
    top_queries: topQueries,
    selected: queries.map((query) => ({
      query,
      count: all.filter((event) => event.query === query).length,
    })),
    totals: {
      searches,
      zero_result: zeroResult,
      errors,
      zero_result_rate: searches ? Number((zeroResult / searches).toFixed(4)) : 0,
      latency_sum: latencySum,
      ok_count: okCount,
      avg_latency_ms: okCount ? Math.round(latencySum / okCount) : 0,
    },
  }
}

function parseSearchParams(params) {
  const kind = params.get('kind')
  const granularity = params.get('granularity') ?? 'day'
  const daysText = params.get('days')
  const limitText = params.get('limit')
  const startText = params.get('start')
  const endText = params.get('end')
  const queries = [...new Set(
    params.getAll('queries').map((item) => item.trim()).filter(Boolean),
  )]
  const days = daysText === null ? 14 : Number(daysText)
  const limit = limitText === null ? 5 : Number(limitText)
  const errors = []

  if (!Number.isInteger(days) || days < 1 || days > MAX_SPAN_DAYS) {
    errors.push({
      loc: ['query', 'days'],
      msg: `Input should be between 1 and ${MAX_SPAN_DAYS}`,
      type: 'less_than_equal',
    })
  }

  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_TOP_QUERIES) {
    errors.push({
      loc: ['query', 'limit'],
      msg: `Input should be between 1 and ${MAX_TOP_QUERIES}`,
      type: 'less_than_equal',
    })
  }

  if (kind !== null && !KINDS.includes(kind)) {
    errors.push({
      loc: ['query', 'kind'],
      msg: "Input should be 'oirf' or 'report'",
      type: 'literal_error',
    })
  }

  if (!GRANULARITIES.includes(granularity)) {
    errors.push({
      loc: ['query', 'granularity'],
      msg: "Input should be 'day', 'week' or 'month'",
      type: 'literal_error',
    })
  }

  const start = startText === null ? null : parseDateText(startText)
  const end = endText === null ? null : parseDateText(endText)

  if (startText !== null && !start) {
    errors.push({
      loc: ['query', 'start'],
      msg: 'Input should be a valid date',
      type: 'date_parsing',
    })
  }

  if (endText !== null && !end) {
    errors.push({
      loc: ['query', 'end'],
      msg: 'Input should be a valid date',
      type: 'date_parsing',
    })
  }

  let error = ''
  if (!errors.length) {
    const rangeEnd = end ?? dayStart(0)
    const rangeStart = start ?? addDays(rangeEnd, -(days - 1))
    if (rangeStart > rangeEnd) {
      error = 'start must be <= end'
    } else if ((rangeEnd - rangeStart) / 86400000 + 1 > MAX_SPAN_DAYS) {
      error = `span: at most ${MAX_SPAN_DAYS} days`
    } else if (queries.length > MAX_QUERIES) {
      error = `queries: at most ${MAX_QUERIES} items`
    }
  }

  return {
    days,
    start,
    end,
    queries,
    kind,
    granularity,
    limit,
    errors,
    error,
  }
}

export default function devStatsMock() {
  return {
    name: 'dev-stats-mock',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url, 'http://localhost')
        if (req.method !== 'GET') return next()

        const isReports = url.pathname === '/api/v1/stats/report-library'
        const isSearch = url.pathname === '/api/v1/stats/search-activity'
        if (!isReports && !isSearch) return next()

        await delay(180)

        const user = tokenUser(req)
        if (!user) return send(res, 401, { detail: 'Not authenticated' })

        if (isReports) return send(res, 200, reportStats())

        const parsed = parseSearchParams(url.searchParams)
        if (parsed.errors.length) return send(res, 422, { detail: parsed.errors })
        if (parsed.error) return send(res, 422, { detail: parsed.error })

        return send(res, 200, searchStats(parsed))
      })

      server.config.logger.info(
        '  stats mock 已启用：GET /api/v1/stats/report-library、GET /api/v1/stats/search-activity（只算 page = 1）',
      )
    },
  }
}
