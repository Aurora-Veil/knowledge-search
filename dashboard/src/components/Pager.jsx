export default function Pager({ page, size, hasPrev, hasNext, disabled, onPrev, onNext }) {
  return (
    <div className="pager">
      <button className="btn" type="button" disabled={disabled || !hasPrev} onClick={onPrev}>
        上一页
      </button>
      <span className="pager-info">
        第 {page} 页 · 每页 {size} 条
      </span>
      <button className="btn" type="button" disabled={disabled || !hasNext} onClick={onNext}>
        下一页
      </button>
    </div>
  )
}
