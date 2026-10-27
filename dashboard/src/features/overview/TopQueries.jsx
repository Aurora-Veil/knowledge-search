import { useMemo } from 'react'
import Chart from '../../components/Chart.jsx'
import ChartCard from './ChartCard.jsx'
import { barColor, chartMotion, chartTheme } from './chartTheme.js'
import { escapeHtml, formatDay, formatNumber, formatWan } from './format.js'

const TOP_N = 5
const EMPTY = []

export default function TopQueries({
  data,
  selectedQuery = '',
  onSelectQuery,
  loading,
  error,
  onRetry,
}) {
  const queries = data?.top_queries ?? EMPTY
  const totals = data?.totals
  const dataUntil = data?.data_until
  const shown = queries.slice(0, TOP_N)

  const option = useMemo(() => {
    const top = queries.slice(0, TOP_N)
    if (!top.length) return null

    const theme = chartTheme()
    const counts = top.map((item) => Number(item.count) || 0)
    const minCount = Math.min(...counts)
    const maxCount = Math.max(...counts)
    return {
      ...chartMotion(),
      grid: { left: 8, right: 60, top: 8, bottom: 4, containLabel: true },
      tooltip: {
        ...theme.tooltip,
        trigger: 'axis',
        axisPointer: {
          type: 'shadow',
          shadowStyle: { color: 'rgba(79, 131, 233, 0.07)' },
          label: { show: false },
        },
        confine: true,
        formatter: (params) => {
          const item = params[0]
          const share =
            totals && totals.searches > 0
              ? ` · 占 ${((Number(item.value) / totals.searches) * 100).toFixed(1)}%`
              : ''
          return `${item.marker}${escapeHtml(item.name)}<br/>${formatNumber(item.value)} 次${share}`
        },
      },
      xAxis: {
        type: 'value',
        minInterval: 1,
        splitNumber: 3,
        splitLine: theme.splitLine,
        axisLine: theme.axisLine,
        axisLabel: { ...theme.axisLabel, formatter: (value) => formatWan(value) },
      },
      yAxis: {
        type: 'category',
        data: top.map((item) => item.query),
        inverse: true,
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: { ...theme.axisLabel, width: 120, overflow: 'truncate' },
      },
      series: [
        {
          type: 'bar',
          data: top.map((item) => {
            const dim = selectedQuery && item.query !== selectedQuery
            return {
              value: item.count,
              itemStyle: {
                color: barColor('azure', item.count, minCount, maxCount),
                opacity: dim ? 0.28 : 1,
              },
              label: { opacity: dim ? 0.35 : 1 },
            }
          }),
          barMaxWidth: 14,
          barMinHeight: 2,
          itemStyle: { borderRadius: [0, 4, 4, 0] },
          emphasis: { ...theme.emphasis, focus: 'series' },
          animationDelay: (index) => index * 45,
          label: {
            show: true,
            position: 'right',
            color: theme.axisLabel.color,
            fontSize: 11,
            formatter: (item) => formatNumber(item.value),
          },
        },
      ],
    }
  }, [queries, totals, selectedQuery])

  function handleSelect(params) {
    if (!onSelectQuery) return
    const row = shown[params.dataIndex]
    if (row) onSelectQuery(row.query)
  }

  return (
    <ChartCard
      title="Top 5 检索词"
      note={dataUntil ? `数据截至 ${formatDay(dataUntil)}` : '近 30 天'}
      loading={loading}
      error={error}
      empty={!shown.length || !totals?.searches}
      emptyText="区间内还没有检索记录。"
      onRetry={onRetry}
    >
      <Chart
        option={option}
        height={260}
        label="Top 5 检索词及次数，点击词条查看趋势"
        onClick={onSelectQuery ? handleSelect : undefined}
      />
    </ChartCard>
  )
}
