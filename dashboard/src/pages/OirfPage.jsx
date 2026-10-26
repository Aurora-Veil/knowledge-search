import { Link } from 'react-router-dom'

export default function OirfPage() {
  return (
    <section className="card placeholder notice">
      <p className="placeholder-title">OIRF 检索已停止维护</p>
      <p className="placeholder-note">
        现在的重点是报告检索。新界面不再提供对象检索和字段树，旧静态页面仍在
        <code>/ui/oirf.html</code>，接口 <code>POST /api/v1/search</code> 也还保留。
      </p>
      <p className="placeholder-note">
        <Link to="/report">去报告检索 →</Link>
      </p>
    </section>
  )
}
