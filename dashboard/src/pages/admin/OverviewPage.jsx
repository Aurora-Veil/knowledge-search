import { useCallback } from "react";
import { Link } from "react-router-dom";
import StatStrip from "../../features/overview/StatStrip.jsx";
import {
  formatNumber,
  formatRate,
  kindName,
} from "../../features/overview/format.js";
import { useStats } from "../../features/overview/useStats.js";
import { DEFAULT_DAYS as DAYS } from "../../features/overview/range.js";
import { getLogSummary } from "../../lib/admin.js";

export default function OverviewPage() {
  const loadSummary = useCallback(() => getLogSummary({ days: DAYS }), []);
  const summary = useStats(loadSummary);

  const data = summary.data;
  const latency = data?.latency_ms;
  const byKind = data?.by_kind ?? [];
  const topErrors = data?.top_errors ?? [];
  const topUsers = data?.top_users ?? [];
  const maxUserSearches = topUsers.reduce(
    (max, row) => Math.max(max, row.searches),
    0,
  );
  const maxErrorCount = topErrors.length ? topErrors[0].count : 0;

  const items = [
    {
      label: "检索请求",
      value: formatNumber(data?.searches),
      note: data?.data_until ? `汇总截至 ${data.data_until}` : "",
    },
    {
      label: "错误率",
      value: formatRate(data?.errors, data?.searches),
      note: data ? `${formatNumber(data.errors)} 次失败` : "",
    },
    {
      label: "P95 延迟",
      value:
        latency?.p95 === null || latency?.p95 === undefined
          ? "—"
          : `${latency.p95} ms`,
      note: data ? `平均 ${data.avg_latency_ms} ms` : "",
    },
    {
      label: "零结果率",
      value: formatRate(data?.zero_result, data?.searches),
      note: data ? `${formatNumber(data.zero_result)} 次无结果` : "",
    },
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">概览</h1>
          <p className="page-sub">后台数据概览</p>
        </div>
      </div>

      <section className="overview-section">
        <div className="section-head">
          <div>
            <h2 className="section-title">最近 {DAYS} 天</h2>
            <p className="section-sub">
              汇总类数据不计算翻页请求，只统计每个检索的第一页结果
            </p>
          </div>
        </div>

        <StatStrip
          items={items}
          loading={summary.loading}
          error={summary.error}
        />
      </section>

      <section className="overview-section">
        <div className="section-head">
          <div>
            <h2 className="section-title">分布</h2>
            <p className="section-sub">按检索类型与失败原因，近 {DAYS} 天</p>
          </div>
        </div>

        <div className="panel-grid">
          <div className="card panel">
            <h3 className="panel-title">按类型</h3>

            {summary.loading && <p className="panel-empty">正在读取…</p>}
            {!summary.loading && summary.error && (
              <p className="panel-empty">{summary.error}</p>
            )}

            {!summary.loading && !summary.error && byKind.length === 0 && (
              <p className="panel-empty">区间内没有检索请求。</p>
            )}

            {!summary.loading && !summary.error && byKind.length > 0 && (
              <div className="table-scroll">
                <table className="data-table data-table--compact">
                  <thead>
                    <tr>
                      <th>类型</th>
                      <th>请求</th>
                      <th>失败</th>
                      <th>错误率</th>
                      <th>零结果率</th>
                      <th>平均耗时</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byKind.map((row) => (
                      <tr key={row.kind}>
                        <td>{kindName(row.kind)}</td>
                        <td className="cell-num">
                          {formatNumber(row.searches)}
                        </td>
                        <td className="cell-num">{formatNumber(row.errors)}</td>
                        <td className="cell-num">
                          {formatRate(row.errors, row.searches)}
                        </td>
                        <td className="cell-num">
                          {formatRate(row.zero_result, row.searches)}
                        </td>
                        <td className="cell-num">{row.avg_latency_ms} ms</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card panel">
            <div className="panel-head">
              <h3 className="panel-title">失败原因</h3>
              <Link className="card-action" to="/admin/errors">
                明细 →
              </Link>
            </div>

            {summary.loading && <p className="panel-empty">正在读取…</p>}
            {!summary.loading && summary.error && (
              <p className="panel-empty">{summary.error}</p>
            )}

            {!summary.loading && !summary.error && topErrors.length === 0 && (
              <p className="panel-empty">区间内没有失败请求。</p>
            )}

            {!summary.loading && !summary.error && topErrors.length > 0 && (
              <div className="error-list">
                {topErrors.map((row) => (
                  <div className="error-row" key={row.error_type}>
                    <span className="error-name">{row.error_type}</span>
                    <span className="error-count">
                      {formatNumber(row.count)}
                    </span>
                    <span className="error-bar">
                      <span
                        style={{
                          width: `${Math.round((row.count / maxErrorCount) * 100)}%`,
                        }}
                      />
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="overview-section">
        <div className="section-head">
          <div>
            <h2 className="section-title">活跃用户</h2>
            <p className="section-sub">近 {DAYS} 天按检索量排名</p>
          </div>
        </div>

        <div className="card panel">
          {summary.loading && <p className="panel-empty">正在读取…</p>}
          {!summary.loading && summary.error && (
            <p className="panel-empty">{summary.error}</p>
          )}

          {!summary.loading && !summary.error && topUsers.length === 0 && (
            <p className="panel-empty">区间内没有带账号的检索记录。</p>
          )}

          {!summary.loading &&
            !summary.error &&
            topUsers.length > 0 &&
            topUsers.map((row, index) => (
              <div className="user-row" key={row.user_id ?? `anon-${index}`}>
                <span
                  className={
                    index === 0 ? "user-rank user-rank--top" : "user-rank"
                  }
                >
                  {index + 1}
                </span>
                <span className="user-name">
                  {row.username ?? (
                    <span className="cell-ghost">
                      用户 {row.user_id} · 已删除
                    </span>
                  )}
                </span>
                <span className="user-bar">
                  <span
                    style={{
                      width: `${Math.round((row.searches / maxUserSearches) * 100)}%`,
                    }}
                  />
                </span>
                <span className="user-meta">
                  {formatNumber(row.searches)}
                  <span className="user-share">
                    {formatRate(row.searches, data?.searches)}
                  </span>
                </span>
              </div>
            ))}
        </div>
      </section>
    </>
  );
}
