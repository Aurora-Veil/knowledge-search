// 分值和命中来源的展示文案。
// 列表和详情都要用，放一处，免得两边改出不一致。

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

// 融合分常在 0.0x，BM25 常在个位数，用同一个格式会没法看
export function formatScore(score) {
  if (typeof score !== 'number' || Number.isNaN(score)) return '—'
  return score >= 1 ? score.toFixed(1) : score.toFixed(4)
}
