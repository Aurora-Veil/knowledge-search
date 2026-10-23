// 和 React 无关的小工具：读写通行证、判断登录后能跳哪。
// 单独放一个文件，方便页面和请求层共用，也方便以后单独测试。

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

// 登录后往哪跳：只认站内路径。
// 以 "/" 开头但 "//" 开头的是协议相对地址，会把用户带到别的站点，必须挡掉。
export function safeNext(raw) {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) {
    return "/report";
  }
  return raw;
}
