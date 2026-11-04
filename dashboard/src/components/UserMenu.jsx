import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { useMcpStatus } from "../features/mcp/useMcpStatus.js";

const DOT_CLASS = {
  up: "is-up",
  down: "is-down",
  checking: "is-checking",
};

/**
 * 账号入口：未登录时是「登录」，已登录时是头像菜单。
 * placement="up" 供侧栏底部，placement="down" 供顶栏右上。
 */
export default function UserMenu({ placement = "up", searchLinks = false }) {
  const { user, loading, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);
  const { state, label, detail, check } = useMcpStatus();

  useEffect(() => {
    if (!open) return;

    function onPointerDown(event) {
      if (!wrapRef.current?.contains(event.target)) {
        setOpen(false);
      }
    }

    function onKeyDown(event) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);

    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  // 校验登录态期间什么都不渲染，避免先闪一下「登录」再变成头像。
  if (loading) return null;

  if (!user) {
    const here = location.pathname + location.search;
    const to =
      location.pathname === "/" ? "/login" : `/login?next=${encodeURIComponent(here)}`;
    return (
      <Link className="user-entry-login" to={to}>
        登录
      </Link>
    );
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next) check();
  }

  function handleLogout() {
    setOpen(false);
    logout();
    navigate("/login", { replace: true });
  }

  const dotClass = DOT_CLASS[state] ?? "";
  const menuClass =
    placement === "down" ? "user-menu user-menu--down" : "user-menu user-menu--up";

  return (
    <div className="user-entry" ref={wrapRef}>
      <button
        type="button"
        className="sidebar-user-trigger"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={toggle}
      >
        <span className="avatar">
          {user.username.slice(0, 1).toUpperCase()}
        </span>
        <span className="user-name">{user.username}</span>
        <span className="user-chevron" aria-hidden="true">
          ⌃
        </span>
      </button>

      {open && (
        <div className={menuClass}>
          <div className="user-menu-head">
            <span className="avatar">
              {user.username.slice(0, 1).toUpperCase()}
            </span>
            <div className="user-menu-identity">
              <div className="user-menu-name">{user.username}</div>
              <div className="user-menu-sub">
                {user.is_active ? "账号正常" : "账号已停用"}
              </div>
            </div>
          </div>

          <div className="user-menu-sep" />

          {searchLinks && (
            <>
              <Link className="user-menu-item" to="/" onClick={() => setOpen(false)}>
                检索首页
              </Link>
              <Link
                className="user-menu-item"
                to="/history"
                onClick={() => setOpen(false)}
              >
                我的记录
              </Link>
              <div className="user-menu-sep" />
            </>
          )}

          {user.role === "admin" && (
            <Link
              className="user-menu-item"
              to="/admin"
              onClick={() => setOpen(false)}
            >
              管理后台
            </Link>
          )}

          <Link
            className="user-menu-item"
            to="/settings"
            onClick={() => setOpen(false)}
          >
            设置
          </Link>

          <button
            type="button"
            className="user-menu-item user-menu-mcp"
            data-tip={`${label} · ${detail}`}
            aria-label={`MCP 服务：${label}。${detail}`}
            onClick={check}
          >
            MCP 服务
            <span className={`status-dot ${dotClass}`} />
          </button>

          <div className="user-menu-sep" />

          <button
            type="button"
            className="user-menu-item is-danger"
            onClick={handleLogout}
          >
            退出登录
          </button>
        </div>
      )}
    </div>
  );
}
