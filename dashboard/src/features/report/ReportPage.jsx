import { useRef, useState } from 'react'
import Pager from '../../components/Pager.jsx'
import { getReport, searchReports } from '../../lib/reports.js'
import ReportDetail from './ReportDetail.jsx'
import ResultList from './ResultList.jsx'
import SearchCard from './SearchCard.jsx'
import { INITIAL_FORM, queryTerms, toSearchBody } from './searchParams.js'

// 列表区的占位：加载中、出错、还没搜、搜不到，共用一套样式
function ListState({ title, note }) {
  return (
    <div className="list-state">
      {title && <p className="placeholder-title">{title}</p>}
      {note && <p className="placeholder-note">{note}</p>}
    </div>
  )
}

export default function ReportPage() {
  // form 是“正在编辑的条件”，submitted 是“上次真正搜出去的条件”。
  // 分开存：改表单不会打乱当前结果，翻页也不会吃进改了一半的输入。
  const [form, setForm] = useState(INITIAL_FORM)
  const [submitted, setSubmitted] = useState(null)

  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')

  // 每发一次请求就自增。回来时编号对不上，说明已经有更新的请求了，丢弃旧结果。
  const searchSeq = useRef(0)
  const detailSeq = useRef(0)

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

  // 列表接口不返回摘要，选中后单独取一次详情
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
    runSearch(submitted, page)
  }

  // 详情接口和行业标签都没有后端高亮，用“上次真正搜出去的词”在前端标
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
      return <ListState title="没有匹配的报告" note="换个说法，或者放宽版式与时间。" />
    }

    return (
      <ResultList
        hits={result.hits}
        selectedId={selectedId}
        onSelect={selectReport}
        terms={terms}
      />
    )
  }

  const selectedHit = result?.hits.find((hit) => hit.report_id === selectedId) ?? null
  const pageCount = result ? Math.max(1, Math.ceil(result.total / result.size)) : 1

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
              {result
                ? `${result.degraded ? '仅词法命中 · ' : ''}共 ${result.total} 条`
                : '按相关度排序'}
            </span>
          </div>

          {renderList()}

          {result && !error && (
            <Pager
              page={result.page}
              pageCount={pageCount}
              size={result.size}
              hasPrev={result.page > 1}
              hasNext={result.page < pageCount}
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
