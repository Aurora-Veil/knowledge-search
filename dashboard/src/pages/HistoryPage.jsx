import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listHistory } from "../lib/reports.js";

const MODE_LABEL = {
  or: "任一匹配",
  and: "全部匹配",
  phrase: "短语匹配",
};

const LIMIT_OPTIONS = [20, 50, 100];

function formatWhen(iso) {
  const date = new Date(iso);
  const diff = Date.now() - date.getTime();

  if (diff < 60 * 1000) return "刚刚";
  if (diff < 60 * 60 * 1000) return `${Math.floor(diff / (60 * 1000))} 分钟前`;
  if (diff < 24 * 60 * 60 * 1000)
    return `${Math.floor(diff / (60 * 60 * 1000))} 小时前`;
  if (diff < 7 * 24 * 60 * 60 * 1000)
    return `${Math.floor(diff / (24 * 60 * 60 * 1000))} 天前`;

  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function describeFilters(filters) {
  const parts = [];

  if (filters.layout) parts.push(filters.layout);
  if (filters.mode) parts.push(MODE_LABEL[filters.mode] ?? filters.mode);
  if (filters.time_weight) parts.push(`时间衰减 ${filters.time_weight}`);
  if (filters.publish_date_from) parts.push(`≥ ${filters.publish_date_from}`);
  if (filters.publish_date_to) parts.push(`≤ ${filters.publish_date_to}`);
  if (filters.industry && filters.industry.length > 0) {
    parts.push(`行业 ${filters.industry.join("、")}`);
  }

  return parts;
}

function searchUrlOf(row) {
  const params = new URLSearchParams();
  params.set("q", row.query);

  const filters = row.filters ?? {};
  if (filters.layout) params.set("layout", filters.layout);
  if (filters.mode) params.set("mode", filters.mode);
  if (filters.time_weight) {
    params.set("decay", String(filters.time_weight));
  }
  if (filters.publish_date_from) {
    params.set("from", filters.publish_date_from);
  }
  if (filters.publish_date_to) {
    params.set("to", filters.publish_date_to);
  }
  if (Array.isArray(filters.industry)) {
    for (const name of filters.industry) {
      params.append("industry", name);
    }
  }

  return `/report?${params.toString()}`;
}

export default function HistoryPage() {
  const [kind, setKind] = useState("report");
  const [limit, setLimit] = useState(20);
  const [tick, setTick] = useState(0);

  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;

    listHistory({ kind, limit })
      .then((data) => {
        if (!alive) return;
        setRows(data);
        setError("");
      })
      .catch((err) => {
        if (!alive) return;
        setError(err.message);
      });

    return () => {
      alive = false;
    };
  }, [kind, limit, tick]);

  function changeKind(value) {
    setRows(null);
    setError("");
    setKind(value);
  }

  function changeLimit(value) {
    setRows(null);
    setError("");
    setLimit(Number(value));
  }

  function refresh() {
    setRows(null);
    setError("");
    setTick((n) => n + 1);
  }

  return (
    <section className="card">
      <p className="lead">一行 = 一次检索，同样的条件重复搜只累加次数</p>

      <div className="history-toolbar">
        <div className="field">
          <label className="field-label" htmlFor="history-kind">
            类型
          </label>
          <select
            id="history-kind"
            className="select"
            value={kind}
            onChange={(event) => changeKind(event.target.value)}
          >
            <option value="report">报告检索</option>
            <option value="oirf">OIRF 检索</option>
          </select>
        </div>

        <div className="field">
          <label className="field-label" htmlFor="history-limit">
            条数
          </label>
          <select
            id="history-limit"
            className="select"
            value={limit}
            onChange={(event) => changeLimit(event.target.value)}
          >
            {LIMIT_OPTIONS.map((value) => (
              <option value={value} key={value}>
                最近 {value} 条
              </option>
            ))}
          </select>
        </div>

        <button type="button" className="btn" onClick={refresh}>
          刷新
        </button>
      </div>

      {error && <p className="form-error">{error}</p>}
      {!rows && !error && <p className="placeholder-note">正在读取…</p>}

      {rows && rows.length === 0 && (
        <div className="placeholder">
          <p className="placeholder-title">还没有搜索记录</p>
          <p className="placeholder-note">去检索页搜一次，这里就会出现。</p>
        </div>
      )}

      {rows && rows.length > 0 && (
        <div className="history-scroll">
          <table className="history-table">
            <thead>
              <tr>
                <th>检索词</th>
                <th>筛选条件</th>
                <th>结果数</th>
                <th>搜索次数</th>
                <th>最后搜索</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="history-query">
                    {(row.kind ?? kind) === "report" ? (
                      <Link
                        className="history-query-btn"
                        to={searchUrlOf(row)}
                        title="用这组条件重新检索"
                      >
                        {row.query}
                      </Link>
                    ) : (
                      row.query
                    )}
                  </td>
                  <td>
                    <div className="history-filters">
                      {describeFilters(row.filters).map((text) => (
                        <span className="chip" key={text}>
                          {text}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="history-num">
                    {row.result_total === null ? (
                      <span className="history-dash">—</span>
                    ) : (
                      row.result_total
                    )}
                  </td>
                  <td className="history-num">{row.search_count}</td>
                  <td className="history-time">
                    {formatWhen(row.last_seen_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
