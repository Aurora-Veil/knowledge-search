export function formatNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : '—'
}

export function formatRate(part, whole) {
  const numerator = Number(part)
  const denominator = Number(whole)
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator <= 0) {
    return '—'
  }
  return `${((numerator / denominator) * 100).toFixed(1)}%`
}

export function formatWan(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  if (Math.abs(number) < 10000) return formatNumber(number)

  const wan = number / 10000
  const text = wan >= 100 ? String(Math.round(wan)) : wan.toFixed(1).replace(/\.0$/, '')
  return `${text}万`
}

export function formatDay(value) {
  return typeof value === 'string' && value.length >= 10 ? value.slice(5, 10) : '—'
}

const ESCAPES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ESCAPES[char])
}
