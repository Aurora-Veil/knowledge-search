import { useEffect, useRef } from 'react'
import { BarChart, LineChart } from 'echarts/charts'
import {
  AxisPointerComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { chartTheme } from '../features/overview/chartTheme.js'

echarts.use([
  BarChart,
  LineChart,
  AxisPointerComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

export default function Chart({
  option,
  height = 220,
  className = '',
  label,
  onClick,
}) {
  const hostRef = useRef(null)
  const chartRef = useRef(null)
  const firstOptionRef = useRef(true)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return undefined

    const chart = echarts.init(host, null, { renderer: 'canvas' })
    chartRef.current = chart
    firstOptionRef.current = true

    let alive = true
    let width = host.clientWidth
    let height = host.clientHeight

    // 首次观察到的尺寸与初始化时一致，跳过 resize，避免打断入场动画
    const resize = () => {
      if (!alive) return
      const nextWidth = host.clientWidth
      const nextHeight = host.clientHeight
      if (nextWidth === width && nextHeight === height) return
      width = nextWidth
      height = nextHeight
      chart.resize()
    }

    const observer = typeof ResizeObserver === 'function'
      ? new ResizeObserver(resize)
      : null

    if (observer) observer.observe(host)
    else window.addEventListener('resize', resize)

    return () => {
      alive = false
      if (observer) observer.disconnect()
      else window.removeEventListener('resize', resize)
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !option) return

    const theme = chartTheme()
    const first = firstOptionRef.current
    chart.setOption(
      {
        color: theme.colors,
        textStyle: theme.textStyle,
        ...option,
        ...(first
          ? {}
          : {
              animationDurationUpdate: 300,
              animationDelayUpdate: 0,
              animationEasingUpdate: 'cubicOut',
            }),
      },
      first ? { notMerge: true } : { notMerge: false },
    )
    firstOptionRef.current = false
  }, [option])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !onClick) return undefined

    chart.on('click', onClick)
    return () => chart.off('click', onClick)
  }, [onClick])

  return (
    <div
      ref={hostRef}
      className={className ? `chart ${className}` : 'chart'}
      style={{
        width: '100%',
        height: typeof height === 'number' ? `${height}px` : height,
        cursor: onClick ? 'pointer' : undefined,
      }}
      role="img"
      aria-label={label}
    />
  )
}
