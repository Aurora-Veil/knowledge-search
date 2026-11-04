import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import UserMenu from "../components/UserMenu.jsx";
import { viewTransitionRunning } from "../lib/viewTransition.js";

const TITLES = {
  "/": "报告检索",
  "/report": "报告检索",
  "/history": "我的记录",
  "/settings": "设置",
};

export default function SearchShell() {
  const { pathname } = useLocation();
  const title = TITLES[pathname] ?? "knowledge-search";

  useEffect(() => {
    document.title = `${title} · knowledge-search`;
  }, [title]);

  // 首页 ↔ 结果页交给 View Transition 处理搜索框的位移，其余换页补一个淡入。
  const animate = !viewTransitionRunning();

  return (
    <div className="search-shell">
      <div className="search-dock">
        <UserMenu placement="down" searchLinks />
      </div>

      <main className="search-content">
        <div className={animate ? "route-in" : undefined} key={pathname}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
