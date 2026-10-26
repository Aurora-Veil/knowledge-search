import { useRef, useState } from 'react'
import Pager from '../../components/Pager.jsx'
import { REPORT_RESULT_WINDOW, getReport, searchReports } from '../../lib/reports.js'
import ReportDetail from './ReportDetail.jsx'
import ResultList from './ResultList.jsx'
import SearchCard from './SearchCard.jsx'
import { INITIAL_FORM, queryTerms, toSearchBody } from './searchParams.js'

function ListState({ title, note }) {
  return (
    <div className="list-state">
      {title && <p className="placeholder-title">{title}</p>}
      {note && <p className="placeholder-note">{note}</p>}
    </div>
  )
}

export default function ReportPage() {
  const [form, setForm] = useState(INITIAL_FORM)
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

  const maxPage = result ? Math.floor(REPORT_RESULT_WINDOW / result.size) : 1

  async function runSearch(values, page) {
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
  }

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

  function handlePage(page) {
    if (!submitted) return
    if (page < 1 || page > maxPage) return
    runSearch(submitted, page)
  }

  const terms = queryTerms(submitted)

  function renderList() {
    if (error) return <ListState title="检索失败" note={error} />
    if (loading) return <ListState note="正在检索…" />
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

  const countText = result
    ? `${result.degraded ? '仅词法命中' : '词法命中'} ${result.total} 条`
    : '按相关度排序'

  return (
    <div className="report">
      <SearchCard
        values={form}
        onChange={(key, value) => setForm((prev) => ({ ...prev, [key]: value }))}
        onSubmit={handleSubmit}
        loading={loading}
      />

      <div className="panes">
        <section className="pane list-pane">
          <div className="list-head">
            <span>{result ? `第 ${result.page} 页 · 每页 ${result.size} 条` : '检索结果'}</span>
            <span className="list-head-note">
              {countText}
              {result && atCeiling
                ? ` · 已到服务端 ${REPORT_RESULT_WINDOW} 条上限`
                : ''}
              {result && !result.degraded && result.hits.length > result.total
                ? ' · 本页含语义召回'
                : ''}
            </span>
          </div>

          {renderList()}

          {result && !error && (result.hits.length > 0 || result.page > 1) && (
            <Pager
              page={result.page}
              size={result.size}
              hasPrev={result.page > 1}
              hasNext={hasNext}
              disabled={loading}
              onPrev={() => handlePage(result.page - 1)}
              onNext={() => handlePage(result.page + 1)}
            />
          )}
        </section>

        <section className="pane detail-pane">
          <ReportDetail
            report={detail}
            hit={selectedHit}
            terms={terms}
            loading={detailLoading}
            error={detailError}
          />
        </section>
      </div>
    </div>
  )
}
