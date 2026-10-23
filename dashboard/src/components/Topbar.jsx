export default function Topbar({ title }) {
  return (
    <header className="topbar">
      <span className="topbar-title">{title}</span>

      <div className="topbar-actions">
        <a className="topbar-link" href="/docs" target="_blank" rel="noopener">
          API 文档
        </a>
      </div>
    </header>
  );
}
