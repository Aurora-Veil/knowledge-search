import { Suspense, useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import ConsoleSidebar from "./ConsoleSidebar.jsx";

const TITLES = {
  "/admin": "概览",
  "/admin/library": "报告库",
  "/admin/search": "检索监控",
  "/admin/errors": "失败请求",
  "/admin/users": "用户管理",
};

export default function ConsoleShell() {
  const { pathname } = useLocation();
  const title = TITLES[pathname] ?? "管理后台";

  useEffect(() => {
    document.title = `${title} · knowledge-search`;
  }, [title]);

  return (
    <div className="shell">
      <ConsoleSidebar />
      <div className="main">
        <main className="content">
          <Suspense fallback={<p className="placeholder-note">正在加载…</p>}>
            <div className="route-in" key={pathname}>
              <Outlet />
            </div>
          </Suspense>
        </main>
      </div>
    </div>
  );
}
