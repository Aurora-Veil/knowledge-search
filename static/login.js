/* 登录 / 注册页。
 *
 * 两个后端接口的形状**不一样**，这是最容易写错的地方：
 *   POST /api/v1/auth/token     form-encoded（OAuth2 密码流）
 *   POST /api/v1/auth/register  JSON
 * 前者用 OAuth2PasswordRequestForm 解析，所以必须发
 * application/x-www-form-urlencoded；发 JSON 会得到 422（缺 username 字段）。
 *
 * 注册成功后顺手登录一次，省得让用户再输一遍密码。
 */

const $ = (id) => document.getElementById(id);

const form = $("authForm");
const usernameInput = $("username");
const passwordInput = $("password");
const confirmField = $("confirmField");
const confirmInput = $("confirm");
const errorEl = $("authError");
const submitBtn = $("authSubmit");
const tabLogin = $("tabLogin");
const tabRegister = $("tabRegister");

/* 当前是登录还是注册 */
let mode = "login";

/* ---------- 登录后往哪跳 ---------- */

/* 只认站内 /ui/ 下的路径。auth.js 那边生成 ?next= 时也只放本页路径，
 * 这里再挡一次：别人直接把 ?next=https://evil 发给你，也不能跳出去。 */
function nextUrl() {
  const raw = new URLSearchParams(location.search).get("next") || "";
  return raw.startsWith("/ui/") ? raw : "/ui/";
}

/* ---------- 显示 ---------- */

function showError(msg) {
  errorEl.textContent = msg;
  errorEl.hidden = false;
}

function clearError() {
  errorEl.hidden = true;
  errorEl.textContent = "";
}

function setMode(next) {
  mode = next;
  const isRegister = mode === "register";

  tabLogin.classList.toggle("active", !isRegister);
  tabRegister.classList.toggle("active", isRegister);

  confirmField.hidden = !isRegister;
  // autocomplete 跟着模式走：登录该用 current-password，注册该用 new-password，
  // 否则浏览器的密码管理器会存错/填错。
  passwordInput.setAttribute("autocomplete", isRegister ? "new-password" : "current-password");
  submitBtn.textContent = isRegister ? "注册并登录" : "登录";

  clearError();
  confirmInput.value = "";
}

function busy(on) {
  submitBtn.disabled = on;
  submitBtn.textContent = on
    ? (mode === "register" ? "注册中…" : "登录中…")
    : (mode === "register" ? "注册并登录" : "登录");
}

/* ---------- 请求 ---------- */

async function login(username, password) {
  const body = new URLSearchParams();
  body.set("username", username);
  body.set("password", password);

  const res = await fetch("/api/v1/auth/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const data = await res.json().catch(() => ({}));

  if (res.status === 401) throw new Error("用户名或密码不对");
  if (res.status === 403) throw new Error("这个账号已停用");
  if (res.status === 503) throw new Error("用户数据库不可用，稍后再试");
  if (!res.ok) throw new Error(errorText(data, "登录失败（HTTP " + res.status + "）"));

  if (!data.access_token) throw new Error("登录响应里没有 access_token");
  return data.access_token;
}

async function register(username, password) {
  const res = await fetch("/api/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json().catch(() => ({}));

  if (res.status === 409) throw new Error("用户名已被占用");
  if (res.status === 503) throw new Error("用户数据库不可用，稍后再试");
  // 422 的 detail 是数组（pydantic 校验），交给 errorText 拍平
  if (!res.ok) throw new Error(errorText(data, "注册失败（HTTP " + res.status + "）"));

  return data;
}

/* ---------- 提交 ---------- */

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearError();

  const username = usernameInput.value.trim();
  const password = passwordInput.value;

  // 先做本地校验，纯粹为了少一次往返；真正的判定在后端
  if (!username) return showError("请填用户名");
  if (!password) return showError("请填密码");

  if (mode === "register") {
    if (password !== confirmInput.value) return showError("两次输入的密码不一样");
  }

  busy(true);
  try {
    if (mode === "register") {
      await register(username, password);
    }
    const token = await login(username, password);
    saveSession(token, username);
    location.replace(nextUrl());
  } catch (err) {
    showError(err.message);
    busy(false);
  }
});

tabLogin.addEventListener("click", () => setMode("login"));
tabRegister.addEventListener("click", () => setMode("register"));

/* ---------- 初始化 ---------- */

// 上次登录过的话，把用户名带上，省得重输（密码不可能带，浏览器也不会给）
usernameInput.value = getUsername();
setMode("login");
usernameInput.focus();
