import { Link } from 'react-router-dom'
import { mockRecentSearches } from '../mock/data.js'

const ENTRIES = [
  {
    to: '/report',
    name: '报告检索',
    desc: '用一句话描述你要找的报告，按语义匹配标题；点开看摘要与原文链接。',
    meta: 'POST /api/v1/reports/search',
  },
  {
    to: '/history',
    name: '搜索记录',
    desc: '一个检索词加一套筛选条件占一行，可以一键用同样的条件重搜。',
    meta: 'GET /api/v1/history',
  },
]

const KIND_LABEL = { report: '报告', oirf: 'OIRF' }

export default function OverviewPage() {
  return (
    <>
      <p className="lead">检索报告、查看最近搜索。旧的 OIRF 对象检索已经停用。</p>

      <div className="entries">
        {ENTRIES.map((entry) => (
          <Link className="entry" key={entry.to} to={entry.to}>
            <div className="entry-name">{entry.name}</div>
            <div className="entry-desc">{entry.desc}</div>
            <div className="entry-meta">{entry.meta}</div>
          </Link>
        ))}
      </div>

      <section className="card">
        <div className="card-head">
          <h2 className="card-title">最近搜索</h2>
          <Link className="card-action" to="/history">
            查看全部
          </Link>
        </div>

        {mockRecentSearches.map((item) => (
          <div className="recent-row" key={item.id}>
            <span className="recent-kind">{KIND_LABEL[item.kind]}</span>
            <div>
              <div className="recent-query">{item.query}</div>
              <div className="recent-filters">{item.filters}</div>
            </div>
            <span className="recent-time">{item.created_at}</span>
          </div>
        ))}
      </section>
    </>
  )
}
