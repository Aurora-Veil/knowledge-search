/* 登录态的公共部分：会话存取、带凭据的 fetch、顶栏用户区。
 *
 * 后端走的是 Bearer token（JWT，见 app/auth/token.py），令牌放在
 * Authorization 头里。这一点决定了本文件的写法：
 *   cookie 是浏览器**自动**带的，Bearer 头必须**手动**加 —— 所以页面里
 *   所有请求都得经过下面的 apiFetch()，不能再用裸 fetch()。
 *
 * 令牌存在 localStorage。
 *   代价说清楚：XSS 一旦得手就能把令牌读走，这比 HttpOnly cookie 差
 *   （docs/auth-learning-path.md §2.4 分析过这个不对称）。之所以还这么选，
 *   是因为后端目前只有 Bearer 一条通道、没有 cookie 通道；要换得连后端一起改。
 *
 * 加载顺序：本文件必须排在页面自己的脚本前面（html 里两个都是 defer，
 * 按出现顺序执行），否则页面脚本用不到 apiFetch。
 */

const TOKEN_KEY = "oirf.token";
const USER_KEY = "oirf.username";

const LOGIN_URL = "/ui/login.html";

/* ---------- 会话 ---------- */

function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

function getUsername() {
  return localStorage.getItem(USER_KEY) || "";
}

function saveSession(token, username) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, username || "");
}

function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/* 登录页地址，带上来路方便登录后跳回去。
 * 只放 pathname + search，不放完整 URL —— 外部 URL 会让登录页变成
 * 开放重定向的跳板（攻击者构造 ?next=https://evil 骗用户点）。 */
function loginUrl() {
  const next = location.pathname + location.search;
  return LOGIN_URL + "?next=" + encodeURIComponent(next);
}

function redirectToLogin() {
  clearSession();
  location.replace(loginUrl());
}

/* ---------- 请求 ---------- */

/* 带凭据的 fetch。
 *
 * 401 一律当成「登录态没了」处理：清掉本地会话、跳登录页，然后把 Response
 * 原样返回 —— 调用方的 !res.ok 分支不用改，但应该在报错前先看 status === 401
 * 并直接 return（页面正在跳转，弹个「凭据无效」再消失反而像出错）。 */
async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", "Bearer " + token);

  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    redirectToLogin();
  }
  return res;
}

/* 进页面先确认有没有令牌。没有就直接跳登录页。
 * 返回值给调用方决定要不要继续做初始化（自动检索、聚焦输入框等）。 */
function requireLogin() {
  if (!getToken()) {
    redirectToLogin();
    return false;
  }
  return true;
}

/* 宽容地读 JSON。
 *
 * FastAPI 自己抛的错是 JSON（{"detail": …}），但**没被捕获的异常**由 uvicorn
 * 兜底，回的是 text/plain 的 "Internal Server Error"。这时候 res.json() 会抛
 * 语法错，一路冒到 catch 里，最后显示给用户的是
 * 「请求失败：Unexpected token 'I' …」—— 排查时毫无信息量。
 * 读不出来就给空对象，让 errorText 退回按状态码报错。 */
async function readJson(res) {
  try {
    return await res.json();
  } catch (err) {
    return {};
  }
}

/* FastAPI 的 detail 有两种形状，前端必须都认：
 *   HTTPException（401/403/404/409…） → detail 是字符串
 *   pydantic 校验失败（422）          → detail 是 [{loc, msg, type}, …]
 * 直接 textContent = detail 会把 422 渲染成 [object Object]。 */
function errorText(data, fallback) {
  const detail = data && data.detail;

  if (typeof detail === "string" && detail) return detail;

  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      if (typeof d === "string") return d;
      // loc 形如 ["body", "password"]，只取最后一段，前面的 body/query 对人没用
      const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : "";
      const msg = (d && d.msg) || "";
      return field ? field + ": " + msg : msg;
    }).filter(Boolean);
    if (parts.length) return parts.join("；");
  }

  return fallback || "请求失败";
}

/* ---------- 顶栏用户区 ---------- */

function logout() {
  clearSession();
  location.replace(LOGIN_URL);
}

/* 渲染 #userBox，并顺手用 /me 验一次令牌。
 * 两种状态都要能用：首页是公开页（未登录也能看入口），所以未登录时
 * 这里显示的是「登录」入口，而不是假装已登录。
 * 为什么要多一次 /me：令牌可能已经过期，而有的页面（OIRF 检索页）进来时
 * 并不发请求 —— 那样用户要等到第一次检索才被踢回登录页。 */
async function mountUser() {
  const box = document.getElementById("userBox");

  // 用 DOM API 而不是拼 innerHTML：用户名是后端校验过的（仅字母数字_-），
  // 但让它有机会进 HTML 解析本身就是不必要的风险。
  if (box) {
    box.replaceChildren();

    if (!getToken()) {
      const login = document.createElement("a");
      login.className = "nav-link";
      login.href = LOGIN_URL;
      login.textContent = "登录";
      box.append(login);
      return;
    }

    const name = document.createElement("span");
    name.className = "user-name";
    name.textContent = getUsername() || "已登录";
    box.append(name);

    const history = document.createElement("a");
    history.className = "nav-link";
    history.href = "/ui/history.html";
    history.textContent = "我的搜索";
    box.append(history);

    const out = document.createElement("a");
    out.className = "nav-link";
    out.href = "#";
    out.textContent = "退出";
    out.addEventListener("click", (e) => {
      e.preventDefault();
      logout();
    });
    box.append(out);
  }

  if (!getToken()) return;

  try {
    const res = await apiFetch("/api/v1/auth/me");
    if (!res.ok) return;                 // 401 已经由 apiFetch 送走；503 不该拦页面
    const me = await res.json();
    if (me && me.username) {
      localStorage.setItem(USER_KEY, me.username);
      if (box) {
        const el = box.querySelector(".user-name");
        if (el) el.textContent = me.username;
      }
    }
  } catch (err) {
    // 网络断了不是登录态问题，交给页面自己的状态条报错
  }
}
