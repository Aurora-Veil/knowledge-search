const SKELETON_BARS = [42, 66, 50, 80, 58, 72, 46, 62]

function ChartSkeleton() {
  return (
    <div className="chart-skeleton" aria-hidden="true">
      <div className="chart-skeleton-lines">
        <span />
        <span />
        <span />
      </div>
      <div className="chart-skeleton-bars">
        {SKELETON_BARS.map((height, index) => (
          <span
            className="chart-skeleton-bar"
            key={index}
            style={{ height: `${height}%` }}
          />
        ))}
      </div>
    </div>
  )
}

export default function ChartCard({
  title,
  note,
  loading,
  error,
  empty,
  emptyText = '接口没有返回可展示的数据。',
  onRetry,
  children,
}) {
  let body = children

  if (error) {
    body = (
      <div className="chart-state">
        <p className="chart-state-title">统计读取失败</p>
        <p className="chart-state-note">{error}</p>
        {onRetry && (
          <button className="btn" type="button" onClick={onRetry}>
            重试
          </button>
        )}
      </div>
    )
  } else if (loading) {
    body = (
      <div className="chart-loading">
        <ChartSkeleton />
        <span className="chart-loading-text">
          <span className="chart-loading-spinner" aria-hidden="true" />
          正在读取统计…
        </span>
      </div>
    )
  } else if (empty) {
    body = (
      <div className="chart-state">
        <p className="chart-state-title">暂无数据</p>
        <p className="chart-state-note">{emptyText}</p>
      </div>
    )
  }

  return (
    <section className="card chart-card" aria-busy={loading || undefined}>
      <div className="chart-head">
        <h3 className="chart-title">{title}</h3>
        {note && <span className="chart-note">{note}</span>}
      </div>
      <div className="chart-body">{body}</div>
    </section>
  )
}
