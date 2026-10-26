import { YEAR_OPTIONS } from './searchParams.js'

export default function SearchCard({ values, onChange, onSubmit, loading }) {
  const canSubmit = values.q.trim() !== '' && !loading

  return (
    <form
      className="search-card"
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
      }}
    >
      <input
        className="input"
        type="search"
        value={values.q}
        onChange={(event) => onChange('q', event.target.value)}
        placeholder="用一句话描述你想要的报告，例如：工业机器人应用场景"
        aria-label="检索词"
      />

      <select
        className="select"
        value={values.layout}
        onChange={(event) => onChange('layout', event.target.value)}
        aria-label="版式"
      >
        <option value="">全部版式</option>
        <option value="横版">横版</option>
        <option value="竖版">竖版</option>
      </select>

      <select
        className="select"
        value={values.mode}
        onChange={(event) => onChange('mode', event.target.value)}
        aria-label="匹配方式"
      >
        <option value="or">任一匹配</option>
        <option value="and">全部匹配</option>
        <option value="phrase">短语匹配</option>
      </select>

      <select
        className="select"
        value={values.date}
        onChange={(event) => onChange('date', event.target.value)}
        aria-label="发布时间"
      >
        <option value="">全部时间</option>
        <option value="1y">近一年</option>
        <option value="3y">近三年</option>
        <option value="5y">近五年</option>
        <optgroup label="按年份">
          {YEAR_OPTIONS.map((year) => (
            <option key={year} value={year}>
              {year} 年
            </option>
          ))}
        </optgroup>
      </select>

      <select
        className="select"
        value={values.decay}
        onChange={(event) => onChange('decay', event.target.value)}
        aria-label="时间权重"
      >
        <option value="">不衰减</option>
        <option value="0.1">略偏新</option>
        <option value="0.2">偏新</option>
        <option value="0.35">更偏新</option>
      </select>

      <button className="btn btn-primary" type="submit" disabled={!canSubmit}>
        {loading ? '检索中…' : '搜索'}
      </button>
    </form>
  )
}
