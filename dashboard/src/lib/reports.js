import { apiFetch, errorText, readJson } from "./api.js";

export const REPORT_RESULT_WINDOW = 200;

export async function searchReports(params) {
  const res = await apiFetch("/api/v1/reports/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });

  const data = await readJson(res);
  if (!res.ok) {
    throw new Error(errorText(data, `检索失败（HTTP ${res.status}）`));
  }
  return data;
}

export async function getReport(reportId) {
  const res = await apiFetch(`/api/v1/reports/${encodeURIComponent(reportId)}`);

  const data = await readJson(res);
  if (!res.ok) {
    throw new Error(errorText(data, `读取报告失败（HTTP ${res.status}）`));
  }
  return data;
}

export async function listHistory({ kind, limit } = {}) {
  const params = new URLSearchParams();
  if (kind) params.set("kind", kind);
  if (limit) params.set("limit", String(limit));

  const query = params.toString();
  const res = await apiFetch(`/api/v1/history${query ? `?${query}` : ""}`);

  const data = await readJson(res);
  if (!res.ok) {
    throw new Error(errorText(data, `读取搜索记录失败（HTTP ${res.status}）`));
  }
  return data;
}
