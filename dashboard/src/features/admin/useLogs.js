import { useEffect, useState } from "react";
import { listLogs } from "../../lib/admin.js";

export const PAGE_SIZE = 50;

/**
 * 检索日志的 keyset 翻页。游标按筛选条件分开存，切筛选自动回到第一页。
 * items 为 null 表示当前条件还没读完。
 */
export function useLogs({ days, kind = "", outcome = "" }) {
  const filterKey = `${days}|${kind}|${outcome}`;

  const [trailState, setTrailState] = useState({ filterKey: "", trail: [""] });
  const trail = trailState.filterKey === filterKey ? trailState.trail : [""];
  const page = trail.length - 1;
  const cursor = trail[page];

  const [state, setState] = useState({ key: "", data: null, error: "" });
  const key = `${filterKey}|${cursor}`;

  useEffect(() => {
    let alive = true;
    const snapshot = key;

    listLogs({ days, kind, outcome, cursor, limit: PAGE_SIZE })
      .then((data) => {
        if (alive) setState({ key: snapshot, data, error: "" });
      })
      .catch((err) => {
        if (alive) {
          setState({
            key: snapshot,
            data: null,
            error: err.message || "读取检索日志失败",
          });
        }
      });

    return () => {
      alive = false;
    };
  }, [key, days, kind, outcome, cursor]);

  const fresh = state.key === key;
  const items = fresh ? (state.data?.items ?? []) : null;
  const nextCursor = fresh ? (state.data?.next ?? null) : null;

  function next() {
    if (!nextCursor) return;
    setTrailState({ filterKey, trail: [...trail, nextCursor] });
  }

  function prev() {
    if (page === 0) return;
    setTrailState({ filterKey, trail: trail.slice(0, -1) });
  }

  return {
    items,
    loading: !fresh,
    error: fresh ? state.error : "",
    hasNext: Boolean(nextCursor),
    page,
    next,
    prev,
  };
}
