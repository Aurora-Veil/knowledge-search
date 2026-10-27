const CURRENT_YEAR = new Date().getFullYear()

export const YEAR_OPTIONS = Array.from({ length: 5 }, (_, index) => String(CURRENT_YEAR - index))

const DAYS_OF = { '1y': 365, '3y': 1095, '5y': 1825 }

export const INITIAL_FORM = {
  q: '',
  layout: '',
  mode: 'or',
  date: '',
  decay: '',
  from: '',
  to: '',
  industry: [],
}

function isoDate(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function dateRangeOf(value) {
  if (!value) return {}

  if (/^\d{4}$/.test(value)) {
    return { publish_date_from: `${value}-01-01`, publish_date_to: `${value}-12-31` }
  }

  const days = DAYS_OF[value]
  if (!days) return {}

  const from = new Date()
  from.setDate(from.getDate() - days)
  return { publish_date_from: isoDate(from) }
}

export function toSearchBody(values, page) {
  const body = {
    q: values.q.trim(),
    page,
    mode: values.mode,
  }

  if (values.layout) body.layout = values.layout
  if (values.decay) body.time_weight = Number(values.decay)
  if (values.industry?.length) body.industry = values.industry

  const dateRange = dateRangeOf(values.date)
  if (!Object.keys(dateRange).length) {
    if (values.from) dateRange.publish_date_from = values.from
    if (values.to) dateRange.publish_date_to = values.to
  }

  return { ...body, ...dateRange }
}

export function queryTerms(values) {
  if (!values) return []
  const q = values.q.trim()
  if (!q) return []
  if (values.mode === 'phrase') return [q]
  return q.split(/\s+/).filter(Boolean)
}
