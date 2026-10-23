// 界面上的筛选项 → 后端请求体。
//
// 后端不认识“近一年”这种说法，只认 YYYY-MM-DD，所以换算全放在这里：
// 组件只管显示和收集，脏活集中在一个纯函数里，好改也好测。

const CURRENT_YEAR = new Date().getFullYear()

// 下来菜单里的年份：今年往前数 5 年，不写死，跨年也不会失效
export const YEAR_OPTIONS = Array.from({ length: 5 }, (_, index) => String(CURRENT_YEAR - index))

// 下拉框的值 → 天数。用“日期减天数”而不是 setFullYear，闰年也准
const DAYS_OF = { '1y': 365, '3y': 1095, '5y': 1825 }

export const INITIAL_FORM = {
  q: '',
  layout: '',
  mode: 'or',
  date: '',
  decay: '',
}

// 只取本地日期，不用 toISOString：那是 UTC，东八区早上 8 点前会差一天
function isoDate(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function dateRangeOf(value) {
  if (!value) return {}

  // 选了具体年份：整年
  if (/^\d{4}$/.test(value)) {
    return { publish_date_from: `${value}-01-01`, publish_date_to: `${value}-12-31` }
  }

  const days = DAYS_OF[value]
  if (!days) return {}

  const from = new Date()
  from.setDate(from.getDate() - days)
  // 近 N 年只要起点，上界交给后端默认的“不限”
  return { publish_date_from: isoDate(from) }
}

// page 由调用方给：新搜索从 1 开始，翻页时是目标页
export function toSearchBody(values, page) {
  const body = {
    q: values.q.trim(),
    page,
    mode: values.mode,
  }

  // 空值不传，后端把“不存在”当成不限
  if (values.layout) body.layout = values.layout
  if (values.decay) body.time_weight = Number(values.decay)

  return { ...body, ...dateRangeOf(values.date) }
}

// 把检索词拆成词表，给前端打标用（markTerms 的第二个参数）。
// phrase 模式整句算一个词，其余模式按空白拆——和后端的切词口径对不齐也没关系，
// 这里只是“把用户输入过的字标黄”，不是重新检索。
export function queryTerms(values) {
  if (!values) return []
  const q = values.q.trim()
  if (!q) return []
  if (values.mode === 'phrase') return [q]
  return q.split(/\s+/).filter(Boolean)
}
