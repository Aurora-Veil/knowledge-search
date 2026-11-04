export default function Pager({ hasPrev, hasNext, disabled, onPrev, onNext }) {
  return (
    <div className="pager">
      <button className="btn" type="button" disabled={disabled || !hasPrev} onClick={onPrev}>
        上一页
      </button>
      <button className="btn" type="button" disabled={disabled || !hasNext} onClick={onNext}>
        下一页
      </button>
    </div>
  )
}
