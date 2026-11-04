import { Link } from "react-router-dom";

export default function ForbiddenPage() {
  return (
    <div className="forbidden-page">
      <section className="card placeholder notice">
        <p className="placeholder-title">没有权限</p>
        <p className="placeholder-note">
          此页面仅对管理员开放，您没有权限访问此页面。
        </p>
        <p className="placeholder-note">
          <Link to="/">回到检索 →</Link>
        </p>
      </section>
    </div>
  );
}
