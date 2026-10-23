import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";

const ITEMS = [
  { to: "/", label: "概览", end: true },
  { to: "/report", label: "报告检索" },
  { to: "/history", label: "搜索记录" },
];

export default function Sidebar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <aside className="sidebar">
      <NavLink className="brand" to="/">
        <span className="brand-mark">KS</span>
        <span className="brand-text">
          <span className="brand-name">knowledge-search</span>
          <span className="brand-sub">报告检索服务</span>
        </span>
      </NavLink>

      <nav className="nav">
        <span className="nav-label">工作台</span>
        {ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              isActive ? "nav-item is-active" : "nav-item"
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-bottom">
        {/* OIRF 检索已停止维护，只留一个小入口给旧链接 */}
        <div className="sidebar-foot">
          <Link className="legacy-link" to="/oirf">
            OIRF 检索（旧版）
          </Link>
          <p className="sidebar-version">静态界面版</p>
        </div>

        {user && (
          <div className="sidebar-user">
            <span className="avatar">
              {user.username.slice(0, 1).toUpperCase()}
            </span>
            <span className="user-name">{user.username}</span>
            <button
              className="user-logout"
              type="button"
              onClick={handleLogout}
            >
              退出
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
