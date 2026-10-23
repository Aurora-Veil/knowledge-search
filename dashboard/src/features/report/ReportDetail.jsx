import { formatScore, matchLabel, scoreLabel } from './format.js'
import HighlightText from './HighlightText.jsx'
import { markTerms, matchesTerm } from './highlight.js'

// 两份数据合起来用：
//   report 来自 GET /reports/{id}，有摘要
//   hit 来自列表，有分值、命中来源
// 后端把摘要从列表里摘掉了，所以详情必须单独请求，这里就得分开放。
// 详情接口也不返回 highlight，标题和摘要只能用当前检索词在前端标。
export default function ReportDetail({ report, hit, terms = [], loading, error }) {
  if (loading) {
    return (
      <div className="detail-empty">
        <p className="placeholder-note">正在读取摘要…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="detail-empty">
        <p className="placeholder-title">摘要读取失败</p>
        <p className="placeholder-note">{error}</p>
      </div>
    )
  }

  if (!report) {
    return (
      <div className="detail-empty">
        <p className="placeholder-title">还没有选中报告</p>
        <p className="placeholder-note">在左侧点一条，这里会显示摘要和原文链接。</p>
      </div>
    )
  }

  return (
    <article>
      <h2 className="detail-title">
        <HighlightText html={markTerms(report.title, terms)} />
      </h2>

      <div className="detail-meta">
        <span>{report.publish_date}</span>
        <span>{report.layout}</span>
        {report.industry.map((name) => (
          <span className={matchesTerm(name, terms) ? 'chip chip-hit' : 'chip'} key={name}>
            {name}
          </span>
        ))}
        {hit && (
          <>
            <span className="chip chip-accent">{matchLabel(hit.match_source)}</span>
            <span>
              {scoreLabel(hit.match_source)} {formatScore(hit.score)}
            </span>
          </>
        )}
      </div>

      <p className="detail-summary">
        <HighlightText html={markTerms(report.summary, terms)} />
      </p>

      <div className="detail-actions">
        <a className="btn btn-primary" href={report.url} target="_blank" rel="noopener">
          打开原文
        </a>
      </div>
    </article>
  )
}
