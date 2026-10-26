import { createContext, useContext, useEffect, useState } from "react";
import { apiFetch, errorText, readJson } from "../lib/api.js";
import { clearSession, getToken, saveSession } from "../lib/auth.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(Boolean(getToken()));

  useEffect(() => {
    let alive = true;

    async function verify() {
      if (!getToken()) {
        setLoading(false);
        return;
      }
      try {
        const res = await apiFetch("/api/v1/auth/me");
        if (!alive) return;
        if (!res.ok) {
          clearSession();
          setUser(null);
          return;
        }
        const me = await readJson(res);
        setUser(me);
      } catch {
      } finally {
        if (alive) setLoading(false);
      }
    }

    verify();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    function onUnauthorized() {
      setUser(null);
    }
    window.addEventListener("oirf:unauthorized", onUnauthorized);
    return () =>
      window.removeEventListener("oirf:unauthorized", onUnauthorized);
  }, []);

  async function login(username, password) {
    const body = new URLSearchParams({ username, password });
    const res = await fetch("/api/v1/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });

    if (res.status === 401) throw new Error("用户名或密码不对");
    if (res.status === 403) throw new Error("这个账号已停用");
    if (res.status === 503) throw new Error("用户数据库不可用，稍后再试");

    const data = await readJson(res);
    if (!res.ok) {
      throw new Error(errorText(data, `登录失败（HTTP ${res.status}）`));
    }
    if (!data.access_token) throw new Error("登录响应里没有 access_token");

    saveSession(data.access_token, username);

    const meRes = await apiFetch("/api/v1/auth/me");
    const me = meRes.ok ? await readJson(meRes) : { username };
    setUser(me);
    return me;
  }

  async function register(username, password) {
    const res = await fetch("/api/v1/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    const data = await readJson(res);

    if (res.status === 409) throw new Error("该用户名已存在");
    if (res.status === 503) throw new Error("用户数据库不可用，稍后再试");
    if (!res.ok) {
      throw new Error(errorText(data, `注册失败（HTTP ${res.status}）`));
    }

    return data;
  }

  function logout() {
    clearSession();
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, register }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth 必须在 AuthProvider 里面使用");
  }
  return context;
}
