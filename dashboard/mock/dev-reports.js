// 假后端：POST /api/v1/reports/search、GET /api/v1/reports/{report_id}
//
// 形状严格照 app/routers/reports.py 抄，目的是让页面代码里没有一行
// “因为没后端所以先这样”的分支：
//
//   · 请求体字段名是 q / layout / mode / page / size / time_weight /
//     publish_date_from / publish_date_to，不是 UI 上的中文标签
//   · 返回 { total, page, size, degraded, hits }
//   · hits 里没有 summary（真后端把它 pop 掉了），摘要必须走详情接口
//   · hits 里可能有 highlight，形如 { title: ["…<em>词</em>…"], summary: [...] }，
//     字段名是 title / industry.text / summary，值是字符串数组；详情接口没有这个字段
//   · 参数校验失败 → 422，detail 是数组；page*size 超窗口 → 400，detail 是字符串
//
// 唯一和真后端不一样的地方是打分：真后端是 Elasticsearch 的 BM25 加 kNN 融合，
// 这里用加权词频代替，只保证排序方向大致一致，页面不该依赖具体分值。
//
// 关掉的办法和 auth mock 一样：启动前设 MOCK_API=0。

import { mockReports } from '../src/mock/data.js'
import { tokenUser } from './dev-auth.js'
import { recordSearch } from './dev-history.js'

// 与 app/search/query_reports.py 的常量对齐
const RESULT_WINDOW = 200
const MAX_SIZE = 100
const LAYOUTS = ['横版', '竖版']
const MODES = ['or', 'and', 'phrase']

// 对应 ES 里的 title^3 industry^2 summary
const FIELD_WEIGHTS = { title: 3, industry: 2, summary: 1 }

// 与 app/search/time_decay.py 对齐：365 天半衰、前 90 天不衰减
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

// pydantic 的 422 detail 是 [{loc, msg, type}]，loc 的第一个元素永远是 body
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

// 一个词在一段文字里出现几次
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

// 真后端的公式是 _score * (1 - w + w * decayDateExp(...))
function decayFactor(publishDate, timeWeight) {
  if (!timeWeight) return 1
  const ageDays = Math.max((Date.now() - Date.parse(`${publishDate}T00:00:00`)) / DAY_MS, 0)
  const overdue = Math.max(ageDays - DECAY_OFFSET_DAYS, 0)
  return 1 - timeWeight + timeWeight * Math.pow(DECAY_HALF, overdue / DECAY_SCALE_DAYS)
}

// 列表卡片：没有 summary，这是有意的
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

// --- 高亮片段 ---
// 真后端由 Elasticsearch 的 highlight 生成，pre_tags 是 <em>、post_tags 是 </em>，
// 字段名是 title / industry.text / summary，值是字符串数组。
// 这里手动造出同样的形状，页面代码不用为 mock 写分支。

const HL_PRE = '<em>'
const HL_POST = '</em>'

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// 一次扫描把所有词都包上，长词优先，避免“机器人”先命中把“工业机器人”切碎
function termRegex(terms) {
  const parts = [...new Set(terms)].filter(Boolean).sort((a, b) => b.length - a.length)
  if (!parts.length) return null
  return new RegExp(parts.map(escapeRegExp).join('|'), 'gi')
}

function markText(text, regex) {
  if (!regex) return text
  return text.replace(regex, (match) => `${HL_PRE}${match}${HL_POST}`)
}

// 摘要太长，只截命中处附近的一小段，像搜索结果的摘要那样
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

  // 后端默认开高亮；highlight: false 时整个字段都不返回
  const useHighlight = body.highlight !== false
  // 短语匹配整串算一个词，不能拆
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
      // total 只统计词法分支，和真后端一致
      total: ranked.length,
      page,
      size,
      // 假的没有向量通道，如实说降级
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

  // 详情接口带 summary，不带 score 系列字段
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

        // 真后端要过 ES，这里也慢一点，方便看加载态
        await delay(250)

        // 报告接口都要求登录，忘了带通行证就是 401
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
        // 真后端在 background task 里记一笔，而且只记成功的（400/422 不记）
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
