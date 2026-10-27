import { useMemo } from 'react'
import Chart from '../../components/Chart.jsx'
import ChartCard from './ChartCard.jsx'
import { barColor, chartMotion, chartTheme } from './chartTheme.js'
import { escapeHtml, formatNumber } from './format.js'

const TOP_N = 8

export default function IndustryChart({
  industries = [],
  industryCount = 0,
  selectedYear = null,
  selectedIndustry = '',
  yearTotal = 0,
  onSelectIndustry,
  loading,
  error,
  onRetry,
}) {
  const shown = industries.slice(0, TOP_N)

  const option = useMemo(() => {
    const top = industries.slice(0, TOP_N)
    if (!top.length) return null

    const theme = chartTheme()
    const counts = top.map((item) => Number(item.count) || 0)
    const minCount = Math.min(...counts)
    const maxCount = Math.max(...counts)
    return {
      ...chartMotion(),
      grid: { left: 8, right: 52, top: 8, bottom: 4, containLabel: true },
      tooltip: {
        ...theme.tooltip,
        trigger: 'axis',
        axisPointer: {
          type: 'shadow',
          shadowStyle: { color: 'rgba(90, 111, 223, 0.07)' },
          label: { show: false },
        },
        confine: true,
        formatter: (params) => {
          const item = params[0]
          const share =
            selectedYear !== null && yearTotal > 0
              ? ` · 占当年 ${((Number(item.value) / yearTotal) * 100).toFixed(1)}%`
              : ''
          return `${item.marker}${escapeHtml(item.name)}<br/>${formatNumber(item.value)} 篇${share}`
        },
      },
      xAxis: {
        type: 'value',
        minInterval: 1,
        splitNumber: 3,
        splitLine: theme.splitLine,
        axisLine: theme.axisLine,
        axisLabel: { ...theme.axisLabel, formatter: (value) => formatNumber(value) },
      },
      yAxis: {
        type: 'category',
        data: top.map((item) => item.name),
        inverse: true,
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: { ...theme.axisLabel, width: 120, overflow: 'truncate' },
      },
      series: [
        {
          type: 'bar',
          data: top.map((item) => {
            const dim = selectedIndustry && item.name !== selectedIndustry
            return {
              value: item.count,
              itemStyle: {
                color: barColor('royal', item.count, minCount, maxCount),
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
  }, [industries, selectedYear, selectedIndustry, yearTotal])

  function handleSelect(params) {
    if (!onSelectIndustry) return
    const row = shown[params.dataIndex]
    if (!row) return
    onSelectIndustry(row.name)
  }

  const notes = []
  if (selectedYear !== null) notes.push(`${selectedYear} 年`)
  if (shown.length) {
    notes.push(
      industryCount > 0
        ? `Top ${shown.length} / 共 ${formatNumber(industryCount)} 个标签`
        : `Top ${shown.length}`,
    )
  }

  return (
    <ChartCard
      title="行业标签"
      note={notes.join(' · ')}
      loading={loading}
      error={error}
      empty={!shown.length}
      emptyText="报告统计里还没有行业数据。"
      onRetry={onRetry}
    >
      <Chart
        option={option}
        height={260}
        label="行业标签 Top 8 的报告数量，点击柱子联动筛选"
        onClick={onSelectIndustry ? handleSelect : undefined}
      />
    </ChartCard>
  )
}
