const FALLBACK = {
  colors: ['#2563eb', '#0ea5e9', '#1e40af', '#60a5fa', '#0369a1', '#93c5fd'],
  text: '#1b1f26',
  text3: '#8b93a1',
  grid: '#f0f1f4',
  tooltip: '#1b1f26',
  font: 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
}

// 柱状图按数值从浅到深取色，不同图表用不同色系的蓝
const BAR_RAMPS = {
  sky: ['#a9d8f2', '#63b7e3', '#2596cd', '#0b6f9e', '#084c6b'],
  royal: ['#b7c4fb', '#8899ef', '#5a6fdf', '#3949bd', '#262f86'],
  azure: ['#bcd2fb', '#83abf4', '#4f83e9', '#2a60d4', '#1c3d94'],
}

function toRgb(hex) {
  const value = hex.replace('#', '')
  return [
    parseInt(value.slice(0, 2), 16),
    parseInt(value.slice(2, 4), 16),
    parseInt(value.slice(4, 6), 16),
  ]
}

function blend(from, to, ratio) {
  const a = toRgb(from)
  const b = toRgb(to)
  const channel = (index) =>
    Math.round(a[index] + (b[index] - a[index]) * ratio)
  return `rgb(${channel(0)}, ${channel(1)}, ${channel(2)})`
}

export function barColor(ramp, value, min, max) {
  const stops = BAR_RAMPS[ramp] ?? BAR_RAMPS.azure
  const low = Number(min)
  const high = Number(max)
  const numeric = Number(value)
  let ratio = 0.5
  if (Number.isFinite(numeric) && Number.isFinite(low) && Number.isFinite(high)) {
    ratio = high > low ? (numeric - low) / (high - low) : 0.5
  }
  ratio = Math.min(1, Math.max(0, ratio))
  const position = ratio * (stops.length - 1)
  const index = Math.min(stops.length - 2, Math.floor(position))
  return blend(stops[index], stops[index + 1], Math.min(1, position - index))
}

function css(name, fallback) {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim()
  return value || fallback
}

export function chartTheme() {
  const fontFamily = css('--font-sans', FALLBACK.font)

  return {
    colors: FALLBACK.colors.map((fallback, index) =>
      css(`--chart-${index + 1}`, fallback),
    ),
    textStyle: {
      color: css('--text', FALLBACK.text),
      fontFamily,
      fontSize: 12,
    },
    danger: css('--danger', '#b42318'),
    axisLabel: {
      color: css('--text-3', FALLBACK.text3),
      fontFamily,
      fontSize: 11,
    },
    axisLine: {
      lineStyle: { color: css('--chart-axis', FALLBACK.text3) },
    },
    splitLine: {
      lineStyle: {
        color: css('--chart-grid', FALLBACK.grid),
        type: 'dashed',
      },
    },
    emphasis: {
      itemStyle: {
        shadowBlur: 14,
        shadowColor: 'rgba(16, 24, 40, 0.22)',
      },
    },
    tooltip: {
      backgroundColor: css('--chart-tooltip', FALLBACK.tooltip),
      borderWidth: 0,
      padding: [9, 11],
      transitionDuration: 0.15,
      extraCssText:
        'border-radius:8px;box-shadow:0 12px 32px rgba(16,24,40,.2);backdrop-filter:blur(6px);',
      textStyle: { color: '#fff', fontFamily, fontSize: 12, lineHeight: 19 },
    },
  }
}

export function chartMotion() {
  const reduce =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  return reduce
    ? { animation: false }
    : {
        animation: true,
        animationDuration: 650,
        animationEasing: 'cubicOut',
      }
}
