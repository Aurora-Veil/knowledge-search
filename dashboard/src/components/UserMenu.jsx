import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { useMcpStatus } from "../features/mcp/useMcpStatus.js";

const DOT_CLASS = {
  up: "is-up",
  down: "is-down",
  checking: "is-checking",
};

export default function UserMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
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

  if (!user) return null;

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

  return (
    <div className="sidebar-user-wrap" ref={wrapRef}>
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
        <div className="user-menu">
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
