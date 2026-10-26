import { apiFetch, errorText, readJson } from "./api.js";

export async function getReportStats() {
  const res = await apiFetch("/api/v1/stats/reports");

  const data = await readJson(res);
  if (!res.ok) {
    throw new Error(errorText(data, `读取报告统计失败（HTTP ${res.status}）`));
  }
  return data;
}

export async function getSearchStats({ days = 14, scope = "all", kind = "" } = {}) {
  const params = new URLSearchParams({
    days: String(days),
    scope,
  });
  if (kind) params.set("kind", kind);

  const res = await apiFetch(`/api/v1/stats/search?${params}`);

  const data = await readJson(res);
  if (!res.ok) {
    throw new Error(errorText(data, `读取检索统计失败（HTTP ${res.status}）`));
  }
  return data;
}
