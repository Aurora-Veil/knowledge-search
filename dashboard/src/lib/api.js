import { clearSession, getToken } from "./auth.js";

export async function readJson(res) {
  try {
    return await res.json();
  } catch {
    return {};
  }
}

export function errorText(data, fallback) {
  const detail = data && data.detail;

  if (typeof detail === "string" && detail) return detail;

  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        const loc = Array.isArray(item.loc)
          ? item.loc[item.loc.length - 1]
          : "";
        const msg = item.msg || "";
        return loc ? `${loc}: ${msg}` : msg;
      })
      .filter(Boolean);
    if (parts.length) return parts.join("；");
  }

  return fallback || "请求失败";
}

export async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(path, { ...options, headers });

  if (res.status === 401) {
    clearSession();
    window.dispatchEvent(new Event("oirf:unauthorized"));
  }

  return res;
}
