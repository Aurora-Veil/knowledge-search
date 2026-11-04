const TOKEN_KEY = "oirf.token";
const USER_KEY = "oirf.username";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function getUsername() {
  return localStorage.getItem(USER_KEY) || "";
}

export function saveSession(token, username) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, username || "");
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function safeNext(raw) {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) {
    return "";
  }
  return raw;
}

/** 没有 next 时的落点：管理员进后台，其余进检索页。 */
export function landingFor(user) {
  return user?.role === "admin" ? "/admin" : "/";
}
