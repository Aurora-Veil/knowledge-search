import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ActivityChart from "../features/overview/ActivityChart.jsx";
import IndustryChart from "../features/overview/IndustryChart.jsx";
import ReportYearsChart from "../features/overview/ReportYearsChart.jsx";
import StatStrip from "../features/overview/StatStrip.jsx";
import TopQueries from "../features/overview/TopQueries.jsx";
import { formatNumber, formatRate } from "../features/overview/format.js";
import { useStats } from "../features/overview/useStats.js";
import { getReportStats, getSearchStats } from "../lib/stats.js";

const ENTRIES = [
  {
    to: "/report",
    name: "报告检索",
    desc: "用一句话描述你要找的报告，按语义匹配标题；点开看摘要与原文链接。",
    meta: "POST /api/v1/reports/search",
  },
  {
    to: "/history",
    name: "搜索记录",
    desc: "一个检索词加一套筛选条件占一行，可以一键用同样的条件重搜。",
    meta: "GET /api/v1/history",
  },
];

function monthOf(value) {
  return typeof value === "string" && value.length >= 7
    ? value.slice(0, 7)
    : "—";
}

export default function OverviewPage() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedYear, setSelectedYear] = useState(null);
  const [selectedIndustry, setSelectedIndustry] = useState("");
  const [selectedQuery, setSelectedQuery] = useState("");

  useEffect(() => {
    let alive = true;

    getReportStats()
      .then((data) => {
        if (alive) setStats(data);
      })
      .catch((err) => {
        if (!alive) return;
        setStats(null);
        setError(err.message || "统计读取失败");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [reloadKey]);

  function reload() {
    setLoading(true);
    setError("");
    setStats(null);
    setReloadKey((value) => value + 1);
  }

  const loadSearch = useCallback(
    () => getSearchStats({ days: 30, kind: "report", limit: 5 }),
    [],
  );
  const search = useStats(loadSearch);

  const loadQuerySearch = useCallback(
    () =>
      selectedQuery
        ? getSearchStats({
            days: 30,
            kind: "report",
            limit: 5,
            queries: [selectedQuery],
          })
        : Promise.resolve(null),
    [selectedQuery],
  );
  const querySearch = useStats(loadQuerySearch);

  const years = stats?.years ?? [];
  const industries = stats?.industries ?? [];
  const range = stats?.publish_range;
  const layouts = stats?.layouts ?? [];

  const canSelectYear = years.some((item) => Array.isArray(item.industries));
  const canSelectIndustry =
    Boolean(stats?.industry_years) ||
    industries.some((item) => Array.isArray(item.years));

  const selectedYearRow =
    selectedYear !== null
      ? years.find((item) => item.year === selectedYear)
      : null;
  const selectedIndustryRow = selectedIndustry
    ? industries.find((item) => item.name === selectedIndustry)
    : null;
  const selectedIndustryDetail = selectedIndustry
    ? stats?.industry_years?.[selectedIndustry]
    : null;
  const selectedIndustryYears =
    selectedIndustryDetail?.years ?? selectedIndustryRow?.years;
  const selectedIndustryCount =
    selectedIndustryDetail?.count ?? selectedIndustryRow?.count ?? 0;

  const chartYears =
    selectedIndustry && Array.isArray(selectedIndustryYears)
      ? years.map((item) => ({
          ...item,
          count:
            selectedIndustryYears.find((row) => row.year === item.year)?.count ??
            0,
        }))
      : years;

  const chartIndustries =
    selectedYearRow && Array.isArray(selectedYearRow.industries)
      ? selectedYearRow.industries
      : industries;

  const toggleYear = useCallback((year) => {
    setSelectedYear((current) => (current === year ? null : year));
  }, []);

  const toggleIndustry = useCallback((name) => {
    setSelectedIndustry((current) => (current === name ? null : name));
  }, []);

  const toggleQuery = useCallback((query) => {
    setSelectedQuery((current) => (current === query ? "" : query));
  }, []);

  const clearFilters = useCallback(() => {
    setSelectedYear(null);
    setSelectedIndustry("");
  }, []);

  const firstYear = years.length ? years[0].year : null;
  const lastYear = years.length ? years[years.length - 1].year : null;

  const layoutText = layouts
    .filter((item) => item.name === "横版" || item.name === "竖版")
    .map((item) => `${item.name} ${formatNumber(item.count)}`)
    .join(" · ");

  const items = [
    {
      label: "报告总数",
      value: formatNumber(stats?.total),
      // note: 'ES 索引内全部报告',
    },
    {
      label: "覆盖年份",
      value:
        firstYear !== null && lastYear !== null
          ? `${firstYear}–${lastYear}`
          : "—",
      // note: years.length ? `${years.length} 个发布年份` : '',
    },
    {
      label: "行业标签",
      value: formatNumber(stats?.industry_count),
      // note: industries.length ? 'Top 8 见图' : '',
    },
    {
      label: "最新发布",
      value: monthOf(range?.to),
      // note: range?.from ? `最早 ${monthOf(range.from)}` : '',
    },
  ];

  const activeSearch = selectedQuery ? querySearch.data : search.data;
  const activeTotals = activeSearch?.totals;
  const activeLoading = selectedQuery
    ? querySearch.loading ||
      (!querySearch.data && !querySearch.error)
    : search.loading;
  const activeError = selectedQuery ? querySearch.error : search.error;
  const activeReload = selectedQuery ? querySearch.reload : search.reload;
  const searchRate = activeTotals
    ? formatRate(activeTotals.zero_result, activeTotals.searches)
    : "—";
  const searchAvg =
    activeTotals && activeTotals.ok_count > 0
      ? `${Math.round(activeTotals.latency_sum / activeTotals.ok_count)} ms`
      : "—";

  return (
    <>
      <p className="lead">这是一行欢迎语句~</p>

      <div className="entries">
        {ENTRIES.map((entry) => (
          <Link className="entry" key={entry.to} to={entry.to}>
            <div className="entry-name">{entry.name}</div>
            <div className="entry-desc">{entry.desc}</div>
            <div className="entry-meta">{entry.meta}</div>
          </Link>
        ))}
      </div>

      <section className="overview-section">
        <div className="section-head">
          <div>
            <h2 className="section-title">报告库</h2>
            <p className="section-sub">
              按发布年份与行业标签统计{layoutText ? ` · ${layoutText}` : ""}
            </p>
          </div>
          <div className="section-tools">
            {selectedYear !== null && (
              <button
                className="filter-chip"
                type="button"
                aria-label={`清除 ${selectedYear} 年筛选`}
                onClick={() => setSelectedYear(null)}
              >
                <span className="filter-chip-label">{selectedYear} 年</span>
                <span className="filter-chip-x" aria-hidden="true">
                  ×
                </span>
              </button>
            )}
            {selectedIndustry && (
              <button
                className="filter-chip"
                type="button"
                aria-label={`清除 ${selectedIndustry} 筛选`}
                onClick={() => setSelectedIndustry("")}
              >
                <span className="filter-chip-label">{selectedIndustry}</span>
                <span className="filter-chip-x" aria-hidden="true">
                  ×
                </span>
              </button>
            )}
            {selectedYear !== null && selectedIndustry && (
              <button
                className="filter-clear"
                type="button"
                onClick={clearFilters}
              >
                清除全部
              </button>
            )}
            {selectedYear === null &&
              !selectedIndustry &&
              (canSelectYear || canSelectIndustry) && (
                <span className="section-hint">点击柱子联动筛选</span>
              )}
          </div>
        </div>

        <StatStrip items={items} loading={loading} error={error} />

        <div className="chart-grid">
          <ReportYearsChart
            years={chartYears}
            total={selectedIndustry ? selectedIndustryCount : stats?.total ?? 0}
            selectedYear={selectedYear}
            selectedIndustry={selectedIndustry}
            onSelectYear={canSelectYear ? toggleYear : undefined}
            loading={loading}
            error={error}
            onRetry={reload}
          />
          <IndustryChart
            industries={chartIndustries}
            industryCount={
              selectedYearRow?.industry_total ?? stats?.industry_count ?? 0
            }
            selectedYear={selectedYear}
            selectedIndustry={selectedIndustry}
            yearTotal={selectedYearRow?.count ?? 0}
            onSelectIndustry={canSelectIndustry ? toggleIndustry : undefined}
            loading={loading}
            error={error}
            onRetry={reload}
          />
        </div>
      </section>

      <section className="overview-section">
        <div className="section-head">
          <div>
            <h2 className="section-title">检索行为</h2>
            <p className="section-sub search-sub">
              <span>{selectedQuery ? `检索词 ${selectedQuery}` : "全站近 30 天"}</span>
              <span>报告检索</span>
              {activeSearch && activeTotals && (
                <>
                  <span>{formatNumber(activeTotals.searches)} 次</span>
                  <span>零结果率 {searchRate}</span>
                  <span>平均耗时 {searchAvg}</span>
                </>
              )}
            </p>
          </div>
          <div className="section-tools">
            {selectedQuery && (
              <button
                className="filter-chip"
                type="button"
                aria-label={`清除检索词 ${selectedQuery} 筛选`}
                onClick={() => setSelectedQuery("")}
              >
                <span className="filter-chip-label">{selectedQuery}</span>
                <span className="filter-chip-x" aria-hidden="true">
                  ×
                </span>
              </button>
            )}
            {!selectedQuery && search.data && (
              <span className="section-hint">点击 Top 5 检索词看趋势</span>
            )}
          </div>
        </div>

        <div className="chart-grid">
          <ActivityChart
            data={activeSearch}
            scopeQuery={selectedQuery}
            loading={activeLoading}
            error={activeError}
            onRetry={activeReload}
          />
          <TopQueries
            data={search.data}
            selectedQuery={selectedQuery}
            onSelectQuery={toggleQuery}
            loading={search.loading}
            error={search.error}
            onRetry={search.reload}
          />
        </div>
      </section>
    </>
  );
}
