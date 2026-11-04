export default function SearchField({
  value,
  onChange,
  onSubmit,
  loading = false,
  autoFocus = false,
  variant = 'bar',
  placeholder = '用一句话描述你想要的报告',
}) {
  const canSubmit = value.trim() !== '' && !loading

  return (
    <form
      className={`search-field is-${variant}`}
      onSubmit={(event) => {
        event.preventDefault()
        if (canSubmit) onSubmit()
      }}
    >
      <svg className="search-field-icon" viewBox="0 0 20 20" aria-hidden="true">
        <circle cx="8.75" cy="8.75" r="5.25" />
        <path d="M12.75 12.75 17 17" />
      </svg>

      <input
        className="search-field-input"
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label="检索词"
        autoFocus={autoFocus}
      />

      <button className="btn btn-primary search-field-btn" type="submit" disabled={!canSubmit}>
        {loading ? '检索中…' : '搜索'}
      </button>
    </form>
  )
}
