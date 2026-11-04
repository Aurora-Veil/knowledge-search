import { lazy } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext.jsx";
import RequireAuth from "./components/RequireAuth.jsx";
import RequireRole from "./components/RequireRole.jsx";
import { ToastProvider } from "./components/Toast.jsx";
import ReportPage from "./features/report/ReportPage.jsx";
import HistoryPage from "./pages/HistoryPage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import SearchHomePage from "./pages/SearchHomePage.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";
import ConsoleShell from "./shells/ConsoleShell.jsx";
import SearchShell from "./shells/SearchShell.jsx";

// 后台页面带 echarts，单独成包，检索端不下载。
const AdminOverviewPage = lazy(() => import("./pages/admin/OverviewPage.jsx"));
const LibraryPage = lazy(() => import("./pages/admin/LibraryPage.jsx"));
const SearchMonitorPage = lazy(() => import("./pages/admin/SearchMonitorPage.jsx"));
const ErrorsPage = lazy(() => import("./pages/admin/ErrorsPage.jsx"));
const UsersPage = lazy(() => import("./pages/admin/UsersPage.jsx"));

export default function App() {
  return (
    <HashRouter>
      <ToastProvider>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />

            {/* 检索端：#/ 公开，其余要登录 */}
            <Route element={<SearchShell />}>
              <Route path="/" element={<SearchHomePage />} />

              <Route element={<RequireAuth />}>
                <Route path="/report" element={<ReportPage />} />
                <Route path="/history" element={<HistoryPage />} />
                <Route path="/settings" element={<SettingsPage />} />
              </Route>
            </Route>

            {/* 后台：管理员 */}
            <Route element={<RequireAuth />}>
              <Route element={<RequireRole role="admin" />}>
                <Route element={<ConsoleShell />}>
                  <Route path="/admin" element={<AdminOverviewPage />} />
                  <Route path="/admin/library" element={<LibraryPage />} />
                  <Route path="/admin/search" element={<SearchMonitorPage />} />
                  <Route path="/admin/errors" element={<ErrorsPage />} />
                  <Route path="/admin/users" element={<UsersPage />} />
                </Route>
              </Route>
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </HashRouter>
  );
}
