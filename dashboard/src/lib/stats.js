import { apiFetch, errorText, readJson } from "./api.js";

/** 检索端首页：报告总量、行业数、发布年份范围。需要登录。 */
export async function getSummary() {
  const res = await apiFetch("/api/v1/stats/summary");

  const data = await readJson(res);
  if (!res.ok) {
    if (res.status === 503) {
      throw new Error("统计服务暂不可用，稍后再试");
    }
    throw new Error(errorText(data, `读取报告统计失败（HTTP ${res.status}）`));
  }
  return data;
}
