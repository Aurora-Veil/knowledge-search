export default function StatStrip({ items, loading, error }) {
  return (
    <div className="stat-strip" aria-busy={loading || undefined}>
      {items.map((item) => {
        const note = error ? '读取失败' : item.note

        return (
          <div className="stat-tile" key={item.label}>
            <div className="stat-label">{item.label}</div>
            {loading ? (
              <span className="stat-value-skeleton" aria-hidden="true" />
            ) : (
              <div className="stat-value">{error ? '—' : item.value}</div>
            )}
            {note ? <div className="stat-note">{note}</div> : null}
          </div>
        )
      })}
    </div>
  )
}
