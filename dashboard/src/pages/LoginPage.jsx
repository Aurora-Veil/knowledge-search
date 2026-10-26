import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { useToast } from "../components/Toast.jsx";
import { getUsername, safeNext } from "../lib/auth.js";

export default function LoginPage() {
  const { login, register } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const next = safeNext(params.get("next"));

  const [username, setUsername] = useState(getUsername());
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState("login");
  const isRegister = mode === "register";

  const [passwordConfirm, setPasswordConfirm] = useState("");

  function switchMode(nextMode) {
    if (nextMode === mode) return;
    setMode(nextMode);
    setPassword("");
    setPasswordConfirm("");
    setError("");
  }

  async function handleSubmit(event) {
    event.preventDefault();

    const name = username.trim();
    if (!name) {
      setError("请填写用户名");
      return;
    }
    if (isRegister && !/^[a-zA-Z0-9_-]{3,32}$/.test(name)) {
      setError("用户名必须是 3-32 位字母、数字、下划线或连字符");
      return;
    }
    if (!password) {
      setError("请填写密码");
      return;
    }

    if (isRegister) {
      if (password.length < 8) return setError("密码至少 8 位");
      if (password.length > 128) return setError("密码不能超过 128 位");
      if (password !== passwordConfirm) return setError("两次输入的密码不一致");
    }

    setError("");
    setBusy(true);

    try {
      if (isRegister) {
        await register(name, password);
        await login(name, password);
        showToast("注册成功，已登录");
      } else {
        await login(name, password);
        showToast("登录成功");
      }
      navigate(next, { replace: true });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  const submitText = busy
    ? isRegister
      ? "注册中…"
      : "登录中…"
    : isRegister
      ? "注册并登录"
      : "登录";

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <span className="brand-mark">KS</span>
          <div>
            <h1 className="login-title">knowledge-search</h1>
            <p className="login-sub">
              {isRegister ? "注册新账号" : "登录已有账号"}
            </p>
          </div>
        </div>

        <div className="login-tabs" role="tablist" aria-label="登录 / 注册">
          <button
            type="button"
            role="tab"
            aria-selected={!isRegister}
            className={isRegister ? "login-tab" : "login-tab is-active"}
            onClick={() => switchMode("login")}
          >
            登录
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={isRegister}
            className={isRegister ? "login-tab is-active" : "login-tab"}
            onClick={() => switchMode("register")}
          >
            注册
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <label className="field">
            <span className="field-label">用户名</span>
            <input
              className="input"
              type="text"
              name="username"
              value={username}
              onChange={(event) => {
                setUsername(event.target.value);
                setError("");
              }}
              autoComplete="username"
              placeholder="3-32 位字母、数字、下划线或连字符"
            />
          </label>

          <label className="field">
            <span className="field-label">密码</span>
            <input
              className="input"
              type="password"
              name="password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                setError("");
              }}
              autoComplete={isRegister ? "new-password" : "current-password"}
              placeholder="至少 8 位"
            />
          </label>

          {isRegister && (
            <label className="field">
              <span className="field-label">确认密码</span>
              <input
                className="input"
                type="password"
                name="passwordConfirm"
                value={passwordConfirm}
                onChange={(event) => {
                  setPasswordConfirm(event.target.value);
                  setError("");
                }}
                autoComplete="new-password"
                placeholder="再输一次密码"
              />
            </label>
          )}

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          <button
            className="btn btn-primary btn-block"
            type="submit"
            disabled={busy}
          >
            {submitText}
          </button>
        </form>

        <p className="login-foot">
          <Link to="/">← 回到概览</Link>
        </p>
      </div>
    </div>
  );
}
