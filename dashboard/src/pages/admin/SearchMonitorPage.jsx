import { useCallback, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PAGE_SIZE, useLogs } from "../../features/admin/useLogs.js";
import ActivityChart from "../../features/overview/ActivityChart.jsx";
import StatStrip from "../../features/overview/StatStrip.jsx";
import TopQueries from "../../features/overview/TopQueries.jsx";
import {
  formatNumber,
  formatRate,
  kindName,
} from "../../features/overview/format.js";
import { DAYS_OPTIONS, DEFAULT_DAYS } from "../../features/overview/range.js";
import { useStats } from "../../features/overview/useStats.js";
import { getLogSummary, getSearchActivity } from "../../lib/admin.js";

function formatWhen(iso) {
  if (typeof iso !== "string" || iso.length < 19) return "—";
  return `${iso.slice(5, 10)} ${iso.slice(11, 19)}`;
}

export default function SearchMonitorPage() {
  const [searchParams] = useSearchParams();

  const [days, setDays] = useState(DEFAULT_DAYS);
  const [kind, setKind] = useState("");
  const [selectedQuery, setSelectedQuery] = useState("");
  const [outcome, setOutcome] = useState(
    searchParams.get("outcome") === "error" ? "error" : "",
  );

  const loadSummary = useCallback(
    () => getLogSummary({ days, kind }),
    [days, kind],
  );
  const summary = useStats(loadSummary);

  const loadActivity = useCallback(
    () => getSearchActivity({ days, kind }),
    [days, kind],
  );
  const activity = useStats(loadActivity);

  const loadScoped = useCallback(
    () =>
      selectedQuery
        ? getSearchActivity({ days, kind, queries: [selectedQuery] })
        : Promise.resolve(null),
    [days, kind, selectedQuery],
  );
  const scoped = useStats(loadScoped);

  const logs = useLogs({ days, kind, outcome });

  const toggleQuery = useCallback((query) => {
    setSelectedQuery((current) => (current === query ? "" : query));
  }, []);

  const trend = selectedQuery ? scoped.data : activity.data;
  const hasTop = Boolean(activity.data?.top_queries?.length);
  const trendLoading = selectedQuery
    ? scoped.loading || (!scoped.data && !scoped.error)
    : activity.loading;
  const trendError = selectedQuery ? scoped.error : activity.error;
  const trendReload = selectedQuery ? scoped.reload : activity.reload;

  const data = summary.data;
  const latency = data?.latency_ms;

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
      note: data ? `P50 ${latency.p50 ?? "—"} ms` : "",
    },
    {
      label: "零结果率",
      value: formatRate(data?.zero_result, data?.searches),
      note: data ? `${formatNumber(data.zero_result)} 次无结果` : "",
    },
  ];

  return (
    <>
      <section className="overview-section">
        <div className="section-head">
          <div>
            <h2 className="section-title">检索监控</h2>
            <p className="section-sub">
              趋势与汇总读按天的小表，明细读原始日志
            </p>
          </div>
          <div className="section-tools">
            <label className="field-inline">
              <span className="field-label">时间</span>
              <select
                className="select"
                value={days}
                onChange={(event) => setDays(Number(event.target.value))}
              >
                {DAYS_OPTIONS.map((value) => (
                  <option value={value} key={value}>
                    近 {value} 天
                  </option>
                ))}
              </select>
            </label>
            <label className="field-inline">
              <span className="field-label">类型</span>
              <select
                className="select"
                value={kind}
                onChange={(event) => setKind(event.target.value)}
              >
                <option value="">全部</option>
                <option value="report">报告检索</option>
                <option value="oirf">OIRF 检索</option>
              </select>
            </label>
          </div>
        </div>

        <StatStrip
          items={items}
          loading={summary.loading}
          error={summary.error}
        />
      </section>

      <section className="overview-section">
        {(selectedQuery || hasTop) && (
          <div className="chart-tools">
            {selectedQuery ? (
              <button
                className="filter-chip"
                type="button"
                aria-label={`清除检索词 ${selectedQuery}`}
                onClick={() => setSelectedQuery("")}
              >
                <span className="filter-chip-label">
                  检索词 {selectedQuery}
                </span>
                <span className="filter-chip-x" aria-hidden="true">
                  ×
                </span>
              </button>
            ) : (
              <span className="section-hint">
                点击 Top 5 检索词，趋势只看这个词
              </span>
            )}
          </div>
        )}

        <div className="chart-grid">
          <ActivityChart
            data={trend}
            scopeQuery={selectedQuery}
            loading={trendLoading}
            error={trendError}
            onRetry={trendReload}
          />
          <TopQueries
            data={activity.data}
            selectedQuery={selectedQuery}
            onSelectQuery={toggleQuery}
            loading={activity.loading}
            error={activity.error}
            onRetry={activity.reload}
          />
        </div>
      </section>

      <section className="overview-section">
        <div className="section-head">
          <div>
            <h2 className="section-title">请求明细</h2>
            <p className="section-sub">
              按时间倒序，汇总表只算第一页请求，翻页不计入
            </p>
          </div>
          <div className="section-tools">
            <label className="field-inline">
              <span className="field-label">结果</span>
              <select
                className="select"
                value={outcome}
                onChange={(event) => setOutcome(event.target.value)}
              >
                <option value="">全部</option>
                <option value="ok">成功</option>
                <option value="error">失败</option>
              </select>
            </label>
          </div>
        </div>

        <div className="card">
          {logs.error && <p className="form-error">{logs.error}</p>}

          {!logs.items && !logs.error && (
            <p className="placeholder-note">正在读取…</p>
          )}

          {logs.items && logs.items.length === 0 && (
            <div className="placeholder">
              <p className="placeholder-title">这个条件下没有请求</p>
              <p className="placeholder-note">
                汇总表只有已经结束的日期，今天的数据要到明天才出现。
              </p>
            </div>
          )}

          {logs.items && logs.items.length > 0 && (
            <>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>时间</th>
                      <th>账号</th>
                      <th>类型</th>
                      <th>检索词</th>
                      <th>结果数</th>
                      <th>耗时</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logs.items.map((row) => (
                      <tr key={row.id}>
                        <td className="cell-time">
                          {formatWhen(row.created_at)}
                        </td>
                        <td>{row.username ?? `用户 ${row.user_id}`}</td>
                        <td>{kindName(row.kind)}</td>
                        <td className="cell-query">{row.query}</td>
                        <td className="cell-num">{row.result_total ?? "—"}</td>
                        <td className="cell-num">{row.latency_ms} ms</td>
                        <td>
                          {row.outcome === "ok" ? (
                            <span className="badge">成功</span>
                          ) : (
                            <span className="badge badge-danger">
                              {row.error_type ?? "失败"}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="table-foot">
                <span className="table-count">
                  第 {logs.page + 1} 页 · 每页 {PAGE_SIZE} 条
                </span>
                <div className="table-actions">
                  <button
                    className="btn"
                    type="button"
                    onClick={logs.prev}
                    disabled={logs.page === 0}
                  >
                    上一页
                  </button>
                  <button
                    className="btn"
                    type="button"
                    onClick={logs.next}
                    disabled={!logs.hasNext}
                  >
                    下一页
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </section>
    </>
  );
}
