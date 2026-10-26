import { apiFetch, errorText, readJson } from "./api.js";

export async function getReportStats() {
  const res = await apiFetch("/api/v1/stats/reports");

  const data = await readJson(res);
  if (!res.ok) {
    throw new Error(errorText(data, `读取报告统计失败（HTTP ${res.status}）`));
  }
  return data;
}

export async function getSearchStats({
  start = "",
  end = "",
  days = 14,
  queries = [],
  scope = "all",
  kind = "",
  granularity = "day",
  limit = 5,
} = {}) {
  const params = new URLSearchParams({
    days: String(days),
    scope,
    granularity,
    limit: String(limit),
  });
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (kind) params.set("kind", kind);
  for (const query of queries) {
    params.append("queries", query);
  }

  const res = await apiFetch(`/api/v1/stats/search?${params}`);

  const data = await readJson(res);
  if (!res.ok) {
    throw new Error(errorText(data, `读取检索统计失败（HTTP ${res.status}）`));
  }
  return data;
}
