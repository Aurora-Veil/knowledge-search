import { useMemo } from "react";
import Chart from "../../components/Chart.jsx";
import ChartCard from "./ChartCard.jsx";
import { chartMotion, chartTheme } from "./chartTheme.js";
import { formatDay, formatNumber, formatRate, formatWan } from "./format.js";

const EMPTY = [];

function dot(color) {
  return `<span style="color:${color}">●</span>`;
}

export default function ActivityChart({
  data,
  scopeQuery = "",
  loading,
  error,
  onRetry,
}) {
  const daily = data?.daily ?? EMPTY;
  const totals = data?.totals;
  const dataUntil = data?.data_until;

  const option = useMemo(() => {
    if (!daily.length) return null;

    const theme = chartTheme();
    const labels = daily.map((row) => formatDay(row.date));
    const success = daily.map((row) =>
      Math.max(0, row.searches - row.zero_result - row.errors),
    );

    return {
      ...chartMotion(),
      grid: { left: 8, right: 14, top: 18, bottom: 4, containLabel: true },
      tooltip: {
        ...theme.tooltip,
        trigger: "axis",
        axisPointer: {
          type: "line",
          lineStyle: {
            color: theme.colors[0],
            width: 1,
            type: "dashed",
            opacity: 0.5,
          },
          label: { show: false },
        },
        confine: true,
        formatter: (params) => {
          const row = daily[params[0]?.dataIndex];
          if (!row) return "";

          return [
            `<strong>${row.date}</strong>`,
            `检索量 ${formatNumber(row.searches)}`,
            `${dot(theme.colors[0])} 有结果 ${formatNumber(success[params[0].dataIndex])}`,
            `${dot(theme.colors[1])} 零结果 ${formatNumber(row.zero_result)}`,
            `${dot(theme.danger)} 失败 ${formatNumber(row.errors)}`,
            `零结果率 ${formatRate(row.zero_result, row.searches)}`,
            `平均耗时 ${
              row.ok_count > 0
                ? `${Math.round(row.latency_sum / row.ok_count)} ms`
                : "—"
            }`,
          ].join("<br/>");
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: labels,
        axisTick: { show: false },
        axisLine: theme.axisLine,
        axisLabel: { ...theme.axisLabel, hideOverlap: true },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        splitNumber: 3,
        splitLine: theme.splitLine,
        axisLabel: {
          ...theme.axisLabel,
          formatter: (value) => formatWan(value),
        },
      },
      series: [
        {
          name: "检索量",
          type: "line",
          data: daily.map((row) => row.searches),
          smooth: 0.35,
          smoothMonotone: "x",
          showSymbol: false,
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { width: 1.5, color: theme.colors[0] },
          itemStyle: { color: theme.colors[0] },
          areaStyle: { color: theme.colors[0], opacity: 0.12 },
          animationDuration: 900,
          animationEasing: "cubicOut",
        },
      ],
    };
  }, [daily]);

  const activeDays = daily.filter((row) => row.searches > 0).length;
  const notes = [];
  if (scopeQuery) notes.push(`检索词：${scopeQuery}`);
  notes.push(
    dataUntil
      ? `数据截至 ${formatDay(dataUntil)} · ${activeDays}/${daily.length} 天有检索`
      : "近 30 天",
  );
  const note = notes.join(" · ");

  return (
    <ChartCard
      title="检索量趋势"
      note={note}
      loading={loading}
      error={error}
      empty={!daily.length || !totals?.searches}
      emptyText="区间内还没有检索记录。"
      onRetry={onRetry}
    >
      <Chart
        option={option}
        height={260}
        label="按天的检索量趋势，悬停查看零结果与失败"
      />
    </ChartCard>
  );
}
