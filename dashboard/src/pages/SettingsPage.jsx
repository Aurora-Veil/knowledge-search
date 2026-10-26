import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";

function formatDate(value) {
  if (!value) return "—";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return date.toLocaleString("zh-CN", { hour12: false });
}

export default function SettingsPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  if (!user) return null;

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="settings-stack">
      <section className="card">
        <div className="settings-head">
          <span className="avatar">
            {user.username.slice(0, 1).toUpperCase()}
          </span>
          <div>
            <div className="settings-name">{user.username}</div>
            <div className="settings-sub">账号设置</div>
          </div>
        </div>

        <div className="settings-row">
          <span className="settings-label">状态</span>
          <span className="settings-value">
            {user.is_active ? "正常" : "已停用"}
          </span>
        </div>

        <div className="settings-row">
          <span className="settings-label">用户 ID</span>
          <span className="settings-value">{user.id}</span>
        </div>

        <div className="settings-row">
          <span className="settings-label">注册时间</span>
          <span className="settings-value">{formatDate(user.created_at)}</span>
        </div>
      </section>

      <section className="card">
        <h2 className="card-title">会话</h2>
        <p className="lead">当前浏览器已登录，退出后需要重新输入密码。</p>
        <div className="settings-actions">
          <button type="button" className="btn" onClick={handleLogout}>
            退出登录
          </button>
        </div>
      </section>
    </div>
  );
}
