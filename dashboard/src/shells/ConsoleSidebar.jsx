import { Link, NavLink } from "react-router-dom";
import UserMenu from "../components/UserMenu.jsx";

const ITEMS = [
  { to: "/admin", label: "概览", end: true },
  { to: "/admin/library", label: "报告库" },
  { to: "/admin/search", label: "检索监控" },
  { to: "/admin/errors", label: "失败请求" },
  { to: "/admin/users", label: "用户管理" },
];

export default function ConsoleSidebar() {
  return (
    <aside className="sidebar">
      <NavLink className="brand" to="/admin">
        <span className="brand-mark">KS</span>
        <span className="brand-text">
          <span className="brand-name">knowledge-search</span>
          <span className="brand-sub">管理后台</span>
        </span>
      </NavLink>

      <nav className="nav">
        <span className="nav-label">后台</span>
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
        <div className="sidebar-foot">
          <Link className="legacy-link" to="/">
            回到检索
          </Link>
          <a
            className="legacy-link"
            href="/docs"
            target="_blank"
            rel="noopener"
          >
            API 文档
          </a>
        </div>

        <div className="sidebar-user-wrap">
          <UserMenu />
        </div>
      </div>
    </aside>
  );
}
