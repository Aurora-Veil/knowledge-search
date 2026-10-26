const MATCH_LABEL = {
  bm25: '词法命中',
  knn: '语义召回',
  both: '双路命中',
}

const SCORE_LABEL = {
  bm25: 'BM25',
  knn: '语义分',
  both: '融合分',
}

export function matchLabel(source) {
  return MATCH_LABEL[source] ?? source ?? '未知来源'
}

export function scoreLabel(source) {
  return SCORE_LABEL[source] ?? '相关度'
}

export function formatScore(score) {
  if (typeof score !== 'number' || Number.isNaN(score)) return '—'
  return score >= 1 ? score.toFixed(1) : score.toFixed(4)
}
