import { mockReports } from '../src/mock/data.js'
import { tokenUser } from './dev-auth.js'
import { recordSearch } from './dev-history.js'

const RESULT_WINDOW = 200
const MAX_SIZE = 100
const LAYOUTS = ['横版', '竖版']
const MODES = ['or', 'and', 'phrase']

const FIELD_WEIGHTS = { title: 3, industry: 2, summary: 1 }

const DAY_MS = 24 * 60 * 60 * 1000
const DECAY_SCALE_DAYS = 365
const DECAY_OFFSET_DAYS = 90
const DECAY_HALF = 0.5

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function send(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(body))
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = []
    req.on('data', (chunk) => chunks.push(chunk))
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
  })
}

function field(key, msg, type) {
  return { loc: ['body', key], msg, type }
}

function validate(body) {
  const errors = []

  if (typeof body.q !== 'string' || !body.q.trim()) {
    errors.push(field('q', 'String should have at least 1 character', 'string_too_short'))
  }

  if (body.page !== undefined) {
    const ok = Number.isInteger(body.page) && body.page >= 1
    if (!ok) {
      errors.push(field('page', 'Input should be greater than or equal to 1', 'greater_than_equal'))
    }
  }

  if (body.size !== undefined) {
    const ok = Number.isInteger(body.size) && body.size >= 1 && body.size <= MAX_SIZE
    if (!ok) {
      errors.push(field('size', 'Input should be between 1 and 100', 'less_than_equal'))
    }
  }

  if (body.mode !== undefined && !MODES.includes(body.mode)) {
    errors.push(field('mode', "Input should be 'or', 'and' or 'phrase'", 'literal_error'))
  }

  if (body.time_weight !== undefined) {
    const ok = typeof body.time_weight === 'number' && body.time_weight >= 0 && body.time_weight <= 1
    if (!ok) {
      errors.push(field('time_weight', 'Input should be between 0 and 1', 'less_than_equal'))
    }
  }

  for (const key of ['publish_date_from', 'publish_date_to']) {
    if (body[key] !== undefined && !DATE_RE.test(String(body[key]))) {
      errors.push(field(key, 'Input should be a valid date', 'date_parsing'))
    }
  }

  return errors
}

function occurrences(text, term) {
  if (!text || !term) return 0
  let count = 0
  let from = 0
  while ((from = text.indexOf(term, from)) !== -1) {
    count += 1
    from += term.length
  }
  return count
}

function matches(report, terms, mode, keyword) {
  const all = `${report.title} ${report.industry.join(' ')} ${report.summary}`.toLowerCase()
  if (mode === 'phrase') return all.includes(keyword)
  if (mode === 'and') return terms.every((term) => all.includes(term))
  return terms.some((term) => all.includes(term))
}

function scoreOf(report, terms) {
  const title = report.title.toLowerCase()
  const industry = report.industry.join(' ').toLowerCase()
  const summary = report.summary.toLowerCase()

  let score = 0
  for (const term of terms) {
    score += occurrences(title, term) * FIELD_WEIGHTS.title
    score += occurrences(industry, term) * FIELD_WEIGHTS.industry
    score += occurrences(summary, term) * FIELD_WEIGHTS.summary
  }
  return score
}

function decayFactor(publishDate, timeWeight) {
  if (!timeWeight) return 1
  const ageDays = Math.max((Date.now() - Date.parse(`${publishDate}T00:00:00`)) / DAY_MS, 0)
  const overdue = Math.max(ageDays - DECAY_OFFSET_DAYS, 0)
  return 1 - timeWeight + timeWeight * Math.pow(DECAY_HALF, overdue / DECAY_SCALE_DAYS)
}

function toCard(report, score, highlight) {
  const rounded = Number(score.toFixed(6))
  const card = {
    report_id: report.report_id,
    title: report.title,
    industry: report.industry,
    layout: report.layout,
    publish_date: report.publish_date,
    url: report.url,
    score: rounded,
    raw_score: rounded,
    knn_score: null,
    match_source: 'bm25',
  }
  if (highlight) card.highlight = highlight
  return card
}

const HL_PRE = '<em>'
const HL_POST = '</em>'

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function termRegex(terms) {
  const parts = [...new Set(terms)].filter(Boolean).sort((a, b) => b.length - a.length)
  if (!parts.length) return null
  return new RegExp(parts.map(escapeRegExp).join('|'), 'gi')
}

function markText(text, regex) {
  if (!regex) return text
  return text.replace(regex, (match) => `${HL_PRE}${match}${HL_POST}`)
}

function snippetOf(text, terms, width = 60) {
  const regex = termRegex(terms)
  if (!regex) return null

  const at = text.search(regex)
  if (at < 0) return null

  const start = Math.max(at - width, 0)
  const end = Math.min(at + width * 2, text.length)
  const slice = text.slice(start, end)

  return (start > 0 ? '…' : '') + markText(slice, termRegex(terms)) + (end < text.length ? '…' : '')
}

function highlightOf(report, terms) {
  const highlight = {}

  const markedTitle = markText(report.title, termRegex(terms))
  if (markedTitle !== report.title) highlight.title = [markedTitle]

  const industryText = report.industry.join(' ')
  const markedIndustry = markText(industryText, termRegex(terms))
  if (markedIndustry !== industryText) highlight['industry.text'] = [markedIndustry]

  const snippet = snippetOf(report.summary, terms)
  if (snippet) highlight.summary = [snippet]

  return Object.keys(highlight).length ? highlight : null
}

function handleSearch(body) {
  const page = body.page ?? 1
  const size = body.size ?? 20

  if (page * size > RESULT_WINDOW) {
    return {
      status: 400,
      body: {
        detail:
          `page*size = ${page * size} exceeds RESULT_WINDOW = ${RESULT_WINDOW}; ` +
          'fusion re-reads that many hits from every retriever to stay page-stable',
      },
    }
  }

  const keyword = body.q.trim().toLowerCase()
  const terms = keyword.split(/\s+/).filter(Boolean)
  const mode = body.mode ?? 'or'
  const timeWeight = body.time_weight ?? 0

  const useHighlight = body.highlight !== false
  const highlightTerms = mode === 'phrase' ? [keyword] : terms

  const ranked = mockReports
    .filter((report) => !body.layout || report.layout === body.layout)
    .filter((report) => !body.publish_date_from || report.publish_date >= body.publish_date_from)
    .filter((report) => !body.publish_date_to || report.publish_date <= body.publish_date_to)
    .filter((report) => matches(report, terms, mode, keyword))
    .map((report) => ({
      report,
      score: scoreOf(report, terms) * decayFactor(report.publish_date, timeWeight),
    }))
    .sort((a, b) => b.score - a.score || b.report.publish_date.localeCompare(a.report.publish_date))

  const start = (page - 1) * size

  return {
    status: 200,
    body: {
      total: ranked.length,
      page,
      size,
      degraded: true,
      hits: ranked
        .slice(start, start + size)
        .map((item) =>
          toCard(item.report, item.score, useHighlight ? highlightOf(item.report, highlightTerms) : null),
        ),
    },
  }
}

function handleDetail(reportId) {
  const report = mockReports.find((item) => item.report_id === reportId)
  if (!report) {
    return { status: 404, body: { detail: `report not found: ${reportId}` } }
  }

  return {
    status: 200,
    body: {
      report_id: report.report_id,
      title: report.title,
      summary: report.summary,
      industry: report.industry,
      layout: report.layout,
      publish_date: report.publish_date,
      url: report.url,
    },
  }
}

export default function devReportsMock() {
  return {
    name: 'dev-reports-mock',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const pathname = new URL(req.url, 'http://localhost').pathname
        const isSearch = req.method === 'POST' && pathname === '/api/v1/reports/search'
        const isDetail = req.method === 'GET' && pathname.startsWith('/api/v1/reports/')
        if (!isSearch && !isDetail) return next()

        await delay(250)

        const user = tokenUser(req)
        if (!user) {
          return send(res, 401, { detail: 'Not authenticated' })
        }

        if (isDetail) {
          const reportId = decodeURIComponent(pathname.slice('/api/v1/reports/'.length))
          const out = handleDetail(reportId)
          return send(res, out.status, out.body)
        }

        let body
        try {
          body = JSON.parse(await readBody(req))
        } catch {
          return send(res, 422, {
            detail: [{ loc: ['body'], msg: 'JSON decode error', type: 'json_invalid' }],
          })
        }
        if (typeof body !== 'object' || body === null) body = {}

        const errors = validate(body)
        if (errors.length) return send(res, 422, { detail: errors })

        const out = handleSearch(body)
        if (out.status === 200) recordSearch(user, body, out.body.total)
        return send(res, out.status, out.body)
      })

      server.config.logger.info(
        '  reports mock 已启用：POST /api/v1/reports/search、GET /api/v1/reports/{id}',
      )
      server.config.logger.info(`  可选版式：${LAYOUTS.join(' / ')}，最大 page*size = ${RESULT_WINDOW}`)
    },
  }
}
