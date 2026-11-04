import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import ForbiddenPage from "../pages/ForbiddenPage.jsx";

/** 角色守卫：未登录交给 RequireAuth，角色不符渲染 403 页，不清会话。 */
export default function RequireRole({ role }) {
  const { user } = useAuth();

  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== role) return <ForbiddenPage />;

  return <Outlet />;
}
