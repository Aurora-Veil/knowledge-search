import { apiFetch, errorText, readJson } from "./api.js";

/** 后台接口：报告库统计、检索监控、用户管理。全部需要管理员。 */

async function request(path, options, fallback) {
  const res = await apiFetch(path, options);
  const data = await readJson(res);

  if (!res.ok) {
    if (res.status === 403) throw new Error("当前账号没有管理员权限");
    if (res.status === 503) throw new Error("服务暂不可用，稍后再试");
    throw new Error(errorText(data, fallback));
  }
  return data;
}

export function getReportStats() {
  return request(
    "/api/v1/admin/stats/report-library",
    undefined,
    "读取报告库统计失败",
  );
}

export function getSearchActivity({
  days = 14,
  kind = "",
  queries = [],
  granularity = "day",
  limit = 5,
} = {}) {
  const params = new URLSearchParams({
    days: String(days),
    granularity,
    limit: String(limit),
  });
  if (kind) params.set("kind", kind);
  for (const query of queries) params.append("queries", query);

  return request(
    `/api/v1/admin/stats/search-activity?${params}`,
    undefined,
    "读取检索趋势失败",
  );
}

export function getLogSummary({ days = 14, kind = "" } = {}) {
  const params = new URLSearchParams({ days: String(days) });
  if (kind) params.set("kind", kind);

  return request(
    `/api/v1/admin/search-logs/summary?${params}`,
    undefined,
    "读取检索汇总失败",
  );
}

export function listLogs({
  days = 14,
  kind = "",
  outcome = "",
  cursor = "",
  limit = 50,
} = {}) {
  const params = new URLSearchParams({ days: String(days), limit: String(limit) });
  if (kind) params.set("kind", kind);
  if (outcome) params.set("outcome", outcome);
  if (cursor) params.set("cursor", cursor);

  return request(
    `/api/v1/admin/search-logs?${params}`,
    undefined,
    "读取检索日志失败",
  );
}

export function listUsers({
  q = "",
  role = "",
  active = "",
  limit = 20,
  offset = 0,
} = {}) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (q) params.set("q", q);
  if (role) params.set("role", role);
  if (active !== "") params.set("active", String(active));

  return request(
    `/api/v1/admin/users?${params}`,
    undefined,
    "读取用户列表失败",
  );
}

export function updateUser(id, patch) {
  return request(
    `/api/v1/admin/users/${id}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    },
    "保存失败",
  );
}
