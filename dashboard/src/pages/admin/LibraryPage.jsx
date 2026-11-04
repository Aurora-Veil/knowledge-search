import { useCallback, useEffect, useState } from "react";
import IndustryChart from "../../features/overview/IndustryChart.jsx";
import ReportYearsChart from "../../features/overview/ReportYearsChart.jsx";
import StatStrip from "../../features/overview/StatStrip.jsx";
import { formatNumber } from "../../features/overview/format.js";
import { getReportStats } from "../../lib/admin.js";

function monthOf(value) {
  return typeof value === "string" && value.length >= 7
    ? value.slice(0, 7)
    : "—";
}

export default function LibraryPage() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedYear, setSelectedYear] = useState(null);
  const [selectedIndustry, setSelectedIndustry] = useState("");

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
    },
    {
      label: "覆盖年份",
      value:
        firstYear !== null && lastYear !== null
          ? `${firstYear}–${lastYear}`
          : "—",
    },
    {
      label: "行业标签",
      value: formatNumber(stats?.industry_count),
    },
    {
      label: "最新发布",
      value: monthOf(range?.to),
    },
  ];

  return (
    <section className="overview-section">
      <div className="section-head">
        <div>
          <h2 className="section-title">报告库</h2>
          <p className="section-sub">
            按发布年份与行业标签统计
            {layoutText ? ` · ${layoutText}` : ""}
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
  );
}
