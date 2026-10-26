import { Link, NavLink } from "react-router-dom";
import UserMenu from "./UserMenu.jsx";

const ITEMS = [
  { to: "/", label: "概览", end: true },
  { to: "/report", label: "报告检索" },
  { to: "/history", label: "搜索记录" },
];

export default function Sidebar() {
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
        <div className="sidebar-foot">
          <Link className="legacy-link" to="/oirf">
            OIRF 检索（旧版）
          </Link>
          <p className="sidebar-version">前端重构版</p>
        </div>

        <UserMenu />
      </div>
    </aside>
  );
}
