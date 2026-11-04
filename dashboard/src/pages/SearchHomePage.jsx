import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import SearchField from "../components/SearchField.jsx";
import { formatNumber } from "../features/overview/format.js";
import { getSummary } from "../lib/stats.js";
import { navigateWithTransition } from "../lib/viewTransition.js";

function yearOf(value) {
  return typeof value === "string" && value.length >= 4
    ? value.slice(0, 4)
    : null;
}

export default function SearchHomePage() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [stats, setStats] = useState(null);

  useEffect(() => {
    if (!user) return;

    let alive = true;
    getSummary()
      .then((data) => {
        if (alive) setStats(data);
      })
      .catch(() => {});

    return () => {
      alive = false;
    };
  }, [user]);

  function submit() {
    const term = q.trim();
    if (!term) return;

    const target = `/report?q=${encodeURIComponent(term)}`;
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(target)}`);
      return;
    }
    navigateWithTransition(navigate, target);
  }

  const from = yearOf(stats?.publish_range?.from);
  const to = yearOf(stats?.publish_range?.to);

  return (
    <div className="search-hero">
      <h1 className="search-hero-title">
        <span className="wordmark-soft">knowledge</span>
        <span className="wordmark-dash">-</span>
        <span className="wordmark-strong">search</span>
      </h1>
      <p className="search-hero-sub">
        一个报告检索系统，收录了大量的行业研究报告，帮助您快速找到所需信息。
      </p>

      <div className="search-hero-field">
        <SearchField
          value={q}
          onChange={setQ}
          onSubmit={submit}
          variant="hero"
          autoFocus
          placeholder="比如：新能源汽车动力电池回收"
        />
      </div>

      {user && stats && (
        <div className="search-hero-stats">
          <span>
            <b>{formatNumber(stats.total)}</b> 份报告
          </span>
          {from && to && (
            <span>
              <b>
                {from}–{to}
              </b>{" "}
              年
            </span>
          )}
          <span>
            <b>{formatNumber(stats.industry_count)}</b> 个行业
          </span>
        </div>
      )}

      {!loading && !user && (
        <p className="search-hero-hint">
          检索需要登录。
          <Link to="/login">直接登录</Link>
        </p>
      )}
    </div>
  );
}
