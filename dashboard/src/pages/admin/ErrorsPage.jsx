import { useCallback, useState } from "react";
import { PAGE_SIZE, useLogs } from "../../features/admin/useLogs.js";
import {
  formatNumber,
  formatRate,
  kindName,
} from "../../features/overview/format.js";
import { useStats } from "../../features/overview/useStats.js";
import { getLogSummary } from "../../lib/admin.js";

const DAYS_OPTIONS = [7, 14, 30];

function formatWhen(iso) {
  if (typeof iso !== "string" || iso.length < 19) return "—";
  return `${iso.slice(5, 10)} ${iso.slice(11, 19)}`;
}

export default function ErrorsPage() {
  const [days, setDays] = useState(7);
  const [kind, setKind] = useState("");

  const loadSummary = useCallback(
    () => getLogSummary({ days, kind }),
    [days, kind],
  );
  const summary = useStats(loadSummary);
  const logs = useLogs({ days, kind, outcome: "error" });

  const data = summary.data;

  return (
    <section className="overview-section">
      <div className="section-head">
        <div>
          <h2 className="section-title">失败请求</h2>
          <p className="section-sub">
            {data
              ? `近 ${days} 天 ${formatNumber(data.errors)} 次失败，错误率 ${formatRate(data.errors, data.searches)}`
              : `近 ${days} 天，按时间倒序`}
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

      <div className="card">
        {logs.error && <p className="form-error">{logs.error}</p>}

        {!logs.items && !logs.error && (
          <p className="placeholder-note">正在读取…</p>
        )}

        {logs.items && logs.items.length === 0 && (
          <div className="placeholder">
            <p className="placeholder-title">这个条件下没有失败请求</p>
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
                    <th>错误</th>
                    <th>HTTP</th>
                    <th>耗时</th>
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
                      <td className="cell-error">{row.error_type ?? "—"}</td>
                      <td className="cell-num">{row.status_code ?? "—"}</td>
                      <td className="cell-num">{row.latency_ms} ms</td>
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
  );
}
