// 报告相关的接口调用。页面只认这里，不直接拼路径、请求头、状态码。
//
// 约定两件事：
//   · 成功返回已经解析好的对象，页面直接拿字段用
//   · 失败 throw，文案优先用后端返回的 detail
//
// 以后换后端地址、加重试、加缓存，都只改这个文件，页面不用动。
import { apiFetch, errorText, readJson } from "./api.js";

// 请求体字段名必须和后端一致：q / page / size / layout / mode /
// time_weight / publish_date_from / publish_date_to
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

// 详情单独取：列表接口的 hits 故意不带 summary
export async function getReport(reportId) {
  const res = await apiFetch(`/api/v1/reports/${encodeURIComponent(reportId)}`);

  const data = await readJson(res);
  if (!res.ok) {
    throw new Error(errorText(data, `读取报告失败（HTTP ${res.status}）`));
  }
  return data;
}

// 搜索记录：GET /api/v1/history?kind=&limit=
//
// 两个坑：
//   · 返回的是裸数组，不是 { items: [...] }
//   · kind 不传代表“全部”，但别传空串，后端只认 report / oirf，空串会 422
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
