import { useEffect, useState } from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import { useToast } from "../../components/Toast.jsx";
import { formatNumber } from "../../features/overview/format.js";
import { listUsers, updateUser } from "../../lib/admin.js";

const PAGE_SIZE = 20;

function formatWhen(iso) {
  if (typeof iso !== "string" || iso.length < 16) return "—";
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)}`;
}

export default function UsersPage() {
  const { user } = useAuth();
  const { showToast } = useToast();

  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [active, setActive] = useState("");
  const [offset, setOffset] = useState(0);

  const [userState, setUserState] = useState({ key: "", data: null, error: "" });
  const [busyId, setBusyId] = useState(null);

  const userKey = `${q}|${role}|${active}|${offset}`;
  const rows = userState.data?.items ?? null;
  const total = userState.data?.total ?? 0;
  const error = userState.error;
  const loading = userState.key !== userKey;

  useEffect(() => {
    let alive = true;
    const key = `${q}|${role}|${active}|${offset}`;

    listUsers({ q, role, active, limit: PAGE_SIZE, offset })
      .then((data) => {
        if (alive) setUserState({ key, data, error: "" });
      })
      .catch((err) => {
        if (alive) {
          setUserState({
            key,
            data: null,
            error: err.message || "读取用户列表失败",
          });
        }
      });

    return () => {
      alive = false;
    };
  }, [q, role, active, offset]);

  function changeFilter(setter, value) {
    setOffset(0);
    setter(value);
  }

  function submitSearch(event) {
    event.preventDefault();
    setOffset(0);
    setQ(qInput.trim());
  }

  async function patch(row, changes, done) {
    setBusyId(row.id);
    try {
      const updated = await updateUser(row.id, changes);
      setUserState((prev) =>
        prev.data
          ? {
              ...prev,
              data: {
                ...prev.data,
                items: prev.data.items.map((item) =>
                  item.id === row.id ? updated : item,
                ),
              },
            }
          : prev,
      );
      showToast(done);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setBusyId(null);
    }
  }

  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <section className="overview-section">
      <div className="section-head">
        <div>
          <h2 className="section-title">用户管理</h2>
          <p className="section-sub">
            共 {formatNumber(total)} 个账号，按 id 排序
          </p>
        </div>
      </div>

      <form className="toolbar" onSubmit={submitSearch}>
        <label className="field-inline">
          <span className="field-label">用户名</span>
          <input
            className="input"
            type="search"
            value={qInput}
            onChange={(event) => setQInput(event.target.value)}
            placeholder="模糊匹配"
          />
        </label>
        <label className="field-inline">
          <span className="field-label">角色</span>
          <select
            className="select"
            value={role}
            onChange={(event) => changeFilter(setRole, event.target.value)}
          >
            <option value="">全部</option>
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </select>
        </label>
        <label className="field-inline">
          <span className="field-label">状态</span>
          <select
            className="select"
            value={active}
            onChange={(event) => changeFilter(setActive, event.target.value)}
          >
            <option value="">全部</option>
            <option value="true">启用</option>
            <option value="false">停用</option>
          </select>
        </label>
        <button className="btn" type="submit">
          查询
        </button>
        <button
          className="btn"
          type="button"
          onClick={() => {
            setQInput("");
            setQ("");
            setRole("");
            setActive("");
            setOffset(0);
          }}
        >
          重置
        </button>
      </form>

      <div className="card">
        {error && <p className="form-error">{error}</p>}

        {!rows && !error && <p className="placeholder-note">正在读取…</p>}

        {rows && rows.length === 0 && (
          <div className="placeholder">
            <p className="placeholder-title">没有匹配的账号</p>
          </div>
        )}

        {rows && rows.length > 0 && (
          <>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>用户名</th>
                    <th>角色</th>
                    <th>状态</th>
                    <th>检索次数</th>
                    <th>最后活跃</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const self = row.id === user?.id;
                    const busy = busyId === row.id;

                    return (
                      <tr key={row.id}>
                        <td className="cell-num">{row.id}</td>
                        <td className="cell-query">{row.username}</td>
                        <td>
                          {row.role === "admin" ? (
                            <span className="badge badge-accent">管理员</span>
                          ) : (
                            <span className="badge">普通用户</span>
                          )}
                        </td>
                        <td>
                          {row.is_active ? (
                            <span className="badge">启用</span>
                          ) : (
                            <span className="badge badge-danger">停用</span>
                          )}
                        </td>
                        <td className="cell-num">
                          {formatNumber(row.search_count)}
                        </td>
                        <td className="cell-time">
                          {formatWhen(row.last_seen_at)}
                        </td>
                        <td>
                          <div className="row-actions">
                            <button
                              className="link-btn"
                              type="button"
                              disabled={self || busy}
                              title={self ? "不能修改自己的角色" : ""}
                              onClick={() =>
                                patch(
                                  row,
                                  { role: row.role === "admin" ? "user" : "admin" },
                                  row.role === "admin"
                                    ? "已改为普通用户"
                                    : "已设为管理员",
                                )
                              }
                            >
                              {row.role === "admin" ? "设为普通" : "设为管理员"}
                            </button>
                            <button
                              className="link-btn"
                              type="button"
                              disabled={self || busy}
                              title={self ? "不能停用自己" : ""}
                              onClick={() =>
                                patch(
                                  row,
                                  { is_active: !row.is_active },
                                  row.is_active ? "已停用" : "已启用",
                                )
                              }
                            >
                              {row.is_active ? "停用" : "启用"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="table-foot">
              <span className="table-count">
                第 {currentPage} / {lastPage} 页
              </span>
              <div className="table-actions">
                <button
                  className="btn"
                  type="button"
                  disabled={offset === 0 || loading}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                >
                  上一页
                </button>
                <button
                  className="btn"
                  type="button"
                  disabled={offset + PAGE_SIZE >= total || loading}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                >
                  下一页
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
