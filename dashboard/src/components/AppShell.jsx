import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar.jsx";
import Topbar from "./Topbar.jsx";

const TITLES = {
  "/": "概览",
  "/report": "报告检索",
  "/oirf": "OIRF 检索（旧版）",
  "/history": "搜索记录",
  "/settings": "设置",
};

export default function AppShell() {
  const { pathname } = useLocation();
  const title = TITLES[pathname] ?? "knowledge-search";

  useEffect(() => {
    document.title = `${title} · knowledge-search`;
  }, [title]);

  return (
    <div className="shell">
      <Sidebar />
      <div className="main">
        <Topbar title={title} />
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
