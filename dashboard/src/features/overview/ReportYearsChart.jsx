import { useMemo } from 'react'
import Chart from '../../components/Chart.jsx'
import ChartCard from './ChartCard.jsx'
import { barColor, chartMotion, chartTheme } from './chartTheme.js'
import { formatNumber } from './format.js'

const CURRENT_YEAR = new Date().getFullYear()

export default function ReportYearsChart({
  years = [],
  total = 0,
  selectedYear = null,
  selectedIndustry = '',
  onSelectYear,
  loading,
  error,
  onRetry,
}) {
  const option = useMemo(() => {
    if (!years.length) return null

    const theme = chartTheme()
    const counts = years.map((item) => Number(item.count) || 0)
    const minCount = Math.min(...counts)
    const maxCount = Math.max(...counts)
    return {
      ...chartMotion(),
      grid: { left: 8, right: 12, top: 16, bottom: 4, containLabel: true },
      tooltip: {
        ...theme.tooltip,
        trigger: 'axis',
        axisPointer: {
          type: 'shadow',
          shadowStyle: { color: 'rgba(37, 99, 235, 0.07)' },
          label: { show: false },
        },
        confine: true,
        formatter: (params) => {
          const item = params[0]
          const count = Number(item.value)
          const share = total > 0 ? ((count / total) * 100).toFixed(1) : '0.0'
          const scope = selectedIndustry ? '占该行业' : '占'
          return `${item.marker}${item.axisValue} 年<br/>${formatNumber(count)} 篇 · ${scope} ${share}%`
        },
      },
      xAxis: {
        type: 'category',
        data: years.map((item) => String(item.year)),
        axisTick: { show: false },
        axisLine: theme.axisLine,
        axisLabel: { ...theme.axisLabel, interval: 0 },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        splitLine: theme.splitLine,
        axisLabel: { ...theme.axisLabel, formatter: (value) => formatNumber(value) },
      },
      series: [
        {
          type: 'bar',
          data: years.map((item) => ({
            value: item.count,
            itemStyle: {
              color: barColor('sky', item.count, minCount, maxCount),
              opacity:
                selectedYear !== null && item.year !== selectedYear ? 0.28 : 1,
            },
          })),
          barMaxWidth: 28,
          barMinHeight: 2,
          itemStyle: { borderRadius: [4, 4, 0, 0] },
          emphasis: theme.emphasis,
          animationDelay: (index) => index * 45,
        },
      ],
    }
  }, [years, total, selectedYear, selectedIndustry])

  function handleSelect(params) {
    if (!onSelectYear) return
    const row = years[params.dataIndex]
    if (!row || row.count <= 0) return
    onSelectYear(row.year)
  }

  const lastYear = years.length ? years[years.length - 1].year : null
  const partial = lastYear === CURRENT_YEAR
  const notes = []
  if (partial) notes.push(`${lastYear} 年为部分年份`)
  if (selectedIndustry) notes.push(`行业：${selectedIndustry}`)

  return (
    <ChartCard
      title="年份分布"
      note={notes.join(' · ') || '按发布年份'}
      loading={loading}
      error={error}
      empty={!years.length}
      emptyText="报告统计里还没有年份数据。"
      onRetry={onRetry}
    >
      <Chart
        option={option}
        height={260}
        label="按发布年份的报告数量，点击柱子联动筛选"
        onClick={onSelectYear ? handleSelect : undefined}
      />
    </ChartCard>
  )
}
