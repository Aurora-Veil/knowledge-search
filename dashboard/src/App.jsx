import { HashRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext.jsx'
import AppShell from './components/AppShell.jsx'
import RequireAuth from './components/RequireAuth.jsx'
import { ToastProvider } from './components/Toast.jsx'
import ReportPage from './features/report/ReportPage.jsx'
import HistoryPage from './pages/HistoryPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import OirfPage from './pages/OirfPage.jsx'
import OverviewPage from './pages/OverviewPage.jsx'

// 用 HashRouter：地址是 /ui/#/report 这种形式，
// 刷新页面时请求的还是 /ui/，不会让 FastAPI 去找不存在的 /ui/report。
export default function App() {
  return (
    <HashRouter>
      <ToastProvider>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />

            {/* 没写 path 的是布局路由：先过门卫，再套壳，最后才是页面 */}
            <Route element={<RequireAuth />}>
              <Route element={<AppShell />}>
                <Route path="/" element={<OverviewPage />} />
                <Route path="/report" element={<ReportPage />} />
                <Route path="/oirf" element={<OirfPage />} />
                <Route path="/history" element={<HistoryPage />} />
              </Route>
            </Route>
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </HashRouter>
  )
}
