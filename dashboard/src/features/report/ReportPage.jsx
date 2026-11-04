import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Pager from '../../components/Pager.jsx'
import SearchField from '../../components/SearchField.jsx'
import { REPORT_RESULT_WINDOW, getReport, searchReports } from '../../lib/reports.js'
import FilterBar from './FilterBar.jsx'
import IndustryTags from './IndustryTags.jsx'
import ReportDetail from './ReportDetail.jsx'
import ResultList from './ResultList.jsx'
import { INITIAL_FORM, queryTerms, toSearchBody } from './searchParams.js'

const MODES = ['or', 'and', 'phrase']

function formFromParams(params) {
  const mode = params.get('mode')
  const date = params.get('date') || ''

  return {
    ...INITIAL_FORM,
    q: params.get('q') || '',
    layout: params.get('layout') || '',
    mode: MODES.includes(mode) ? mode : 'or',
    date,
    decay: params.get('decay') || '',
    from: date ? '' : params.get('from') || '',
    to: date ? '' : params.get('to') || '',
    industry: params.getAll('industry'),
  }
}

function ListState({ title, note }) {
  return (
    <div className="list-state">
      {title && <p className="placeholder-title">{title}</p>}
      {note && <p className="placeholder-note">{note}</p>}
    </div>
  )
}

export default function ReportPage() {
  const [searchParams] = useSearchParams()
  const preset = useMemo(() => formFromParams(searchParams), [searchParams])
  const [form, setForm] = useState(preset)
  const [submitted, setSubmitted] = useState(null)

  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')

  const searchSeq = useRef(0)
  const detailSeq = useRef(0)
  const lastPresetRef = useRef('')

  const maxPage = result ? Math.floor(REPORT_RESULT_WINDOW / result.size) : 1

  const runSearch = useCallback(async (values, page) => {
    const seq = ++searchSeq.current
    setLoading(true)
    setError('')

    try {
      const data = await searchReports(toSearchBody(values, page))
      if (seq !== searchSeq.current) return
      setResult(data)
      setSubmitted(values)
      setSelectedId('')
      setDetail(null)
    } catch (err) {
      if (seq !== searchSeq.current) return
      setError(err.message)
    } finally {
      if (seq === searchSeq.current) setLoading(false)
    }
  }, [])

  // 从搜索记录跳进来时，按 URL 里的条件直接检索一次
  useEffect(() => {
    if (!preset.q.trim()) return

    const key = searchParams.toString()
    if (!key || key === lastPresetRef.current) return

    lastPresetRef.current = key
    setForm(preset)
    runSearch(preset, 1)
  }, [preset, searchParams, runSearch])

  async function selectReport(reportId) {
    const seq = ++detailSeq.current
    setSelectedId(reportId)
    setDetail(null)
    setDetailLoading(true)
    setDetailError('')

    try {
      const data = await getReport(reportId)
      if (seq !== detailSeq.current) return
      setDetail(data)
    } catch (err) {
      if (seq !== detailSeq.current) return
      setDetailError(err.message)
    } finally {
      if (seq === detailSeq.current) setDetailLoading(false)
    }
  }

  function handleSubmit() {
    if (!form.q.trim()) return
    runSearch({ ...form }, 1)
  }

  function changeForm(key, value) {
    setForm((prev) => {
      const next = { ...prev, [key]: value }
      if (key === 'date') {
        next.from = ''
        next.to = ''
      }
      return next
    })
  }

  function clearExtraFilters() {
    setForm((prev) => ({ ...prev, from: '', to: '', industry: [] }))
  }

  function handlePage(page) {
    if (!submitted) return
    if (page < 1 || page > maxPage) return
    runSearch(submitted, page)
  }

  const terms = queryTerms(submitted)

  function renderList() {
    if (error) return <ListState title="检索失败" note={error} />
    if (loading) {
      return (
        <div className="skeleton-list" aria-busy="true" aria-label="正在检索">
          {[0, 1, 2, 3].map((n) => (
            <div key={n}>
              <span className="skeleton skeleton-title" />
              <span className="skeleton skeleton-text" />
              <span className="skeleton skeleton-meta" />
            </div>
          ))}
        </div>
      )
    }
    if (!result) {
      return (
        <ListState title="输入检索词开始" note="支持空格分隔多个词，例如：工业机器人 应用场景" />
      )
    }
    if (!result.hits.length) {
      return result.page > 1 ? (
        <ListState title="这一页没有内容了" note="返回上一页继续看。" />
      ) : (
        <ListState title="没有匹配的报告" note="换个说法，或者放宽版式与时间。" />
      )
    }

    return (
      <ResultList
        hits={result.hits}
        startIndex={(result.page - 1) * result.size}
        selectedId={selectedId}
        onSelect={selectReport}
        terms={terms}
      />
    )
  }

  const selectedHit = result?.hits.find((hit) => hit.report_id === selectedId) ?? null

  const atCeiling = result
    ? result.page >= maxPage && result.hits.length === result.size
    : false
  const hasNext = result
    ? result.hits.length === result.size && !atCeiling
    : false

  function closeDetail() {
    detailSeq.current += 1
    setSelectedId('')
    setDetail(null)
    setDetailError('')
    setDetailLoading(false)
  }

  const extraFilters =
    Boolean(form.from) || Boolean(form.to) || form.industry.length > 0

  return (
    <div className="report">
      <SearchField
        value={form.q}
        onChange={(value) => changeForm('q', value)}
        onSubmit={handleSubmit}
        loading={loading}
      />

      {extraFilters && (
        <div className="preset-bar">
          <span className="preset-label">附加筛选</span>
          {form.from && <span className="chip">≥ {form.from}</span>}
          {form.to && <span className="chip">≤ {form.to}</span>}
          {form.industry.map((name) => (
            <span className="chip" key={name}>
              {name}
            </span>
          ))}
          <button
            className="preset-clear"
            type="button"
            onClick={clearExtraFilters}
          >
            清除
          </button>
        </div>
      )}

      <div className="result-bar">
        {result ? (
          <span className="list-count">
            {result.total}
            <small>条结果</small>
          </span>
        ) : (
          <span className="list-count">检索结果</span>
        )}

        <span className="list-head-note">
          {result ? `第 ${result.page} 页 · 每页 ${result.size} 条` : '按相关度排序'}
          {result && result.degraded ? ' · 仅词法命中' : ''}
          {result && atCeiling ? ` · 已到服务端 ${REPORT_RESULT_WINDOW} 条上限` : ''}
          {result && !result.degraded && result.hits.length > result.total
            ? ' · 本页含语义召回'
            : ''}
        </span>

        <FilterBar values={form} onChange={changeForm} />
      </div>

      {result && !error && result.hits.length > 0 && <IndustryTags hits={result.hits} />}

      <div className={selectedId ? 'panes is-split' : 'panes'}>
        <section className="pane list-pane">
          {renderList()}

          {result && !error && (result.hits.length > 0 || result.page > 1) && (
            <Pager
              hasPrev={result.page > 1}
              hasNext={hasNext}
              disabled={loading}
              onPrev={() => handlePage(result.page - 1)}
              onNext={() => handlePage(result.page + 1)}
            />
          )}
        </section>

        {selectedId && (
          <section className="pane detail-pane">
            <ReportDetail
              report={detail}
              hit={selectedHit}
              terms={terms}
              loading={detailLoading}
              error={detailError}
              onClose={closeDetail}
            />
          </section>
        )}
      </div>
    </div>
  )
}
