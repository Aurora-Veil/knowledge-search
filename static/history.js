/* 我的搜索记录页。
 *
 * 数据来自 GET /api/v1/history?kind=&limit=（见 app/routers/history.py）。
 * 后端存的是**检索条件**，不是检索结果 —— 所以这一页能做的是「按同样的条件
 * 再搜一次」，而不是「看当时的结果快照」。
 */

const $ = (id) => document.getElementById(id);

const kindSel = $("kind");
const limitSel = $("limit");
const reloadBtn = $("reload");
const statusEl = $("historyStatus");
const tableEl = $("historyTable");
const tbody = $("historyBody");

const KIND_LABEL = { oirf: "OIRF", report: "报告" };

/* ---------- 小工具 ---------- */

function showStatus(msg, kind) {
  statusEl.textContent = msg;
  statusEl.className = "status" + (kind ? " " + kind : "");
  statusEl.hidden = false;
}

function clearStatus() {
  statusEl.hidden = true;
  statusEl.textContent = "";
}

/* last_seen_at / first_seen_at 是 TIMESTAMPTZ，FastAPI 序列化成带时区的 ISO 串。
 * 转成本地时间显示：直接显示 ISO 串会让用户以为时间错了 8 小时。 */
function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
         " " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
}

/* filters 是 JSONB，形状随检索接口而变（对象里可能套数组）。
 * 这里只做人能读的扁平化，不做解释 —— 列出来是为了「信息别丢」，不是为了好看。 */
function fmtFilters(filters) {
  if (!filters || typeof filters !== "object" || Array.isArray(filters)) return "";
  const parts = Object.entries(filters).map(([k, v]) => {
    const val = Array.isArray(v) ? v.join(" / ") : String(v);
    return k + "=" + val;
  });
  return parts.join("　");
}

/* 重搜链接：只带表单能表达的字段，多加一个 go=1 让目标页自动开搜。
 * 具体值会在目标页再过一遍白名单（认不出来的值退回默认），
 * 免得手改 URL 塞个 type=foo 进去被后端 422。 */
function replayUrl(row) {
  const f = (row.filters && typeof row.filters === "object" && !Array.isArray(row.filters))
    ? row.filters : {};

  const p = new URLSearchParams();
  if (row.query) p.set("q", row.query);
  if (f.mode) p.set("mode", f.mode);

  if (row.kind === "oirf") {
    if (f.type) p.set("type", f.type);
    p.set("go", "1");
    return "/ui/oirf.html?" + p.toString();
  }

  if (f.layout) p.set("layout", f.layout);
  p.set("go", "1");
  return "/ui/report.html?" + p.toString();
}

/* ---------- 渲染 ---------- */

function render(rows) {
  tbody.replaceChildren();

  if (!rows.length) {
    tableEl.hidden = true;
    const filter = kindSel.value ? "（当前只看" + KIND_LABEL[kindSel.value] + "）" : "";
    showStatus("还没有搜索记录" + filter + "。去 OIRF 检索或报告检索搜一次，这里就会有了。");
    return;
  }

  for (const row of rows) {
    const tr = document.createElement("tr");

    // 最近一次。去重之后一行可能被搜过很多次，第一次的时间放进 title
    const time = document.createElement("td");
    time.className = "col-time";
    time.textContent = fmtTime(row.last_seen_at);
    time.title = "第一次：" + fmtTime(row.first_seen_at) +
                 "　共 " + row.search_count + " 次";
    tr.append(time);

    // 类型
    const kind = document.createElement("td");
    kind.className = "col-kind";
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = KIND_LABEL[row.kind] || row.kind;
    kind.append(badge);
    tr.append(kind);

    // 检索词（OIRF 允许留空 = 按类型浏览，所以空要说清楚，不能显示成空白）
    const query = document.createElement("td");
    query.className = "col-query";
    if (row.query) {
      query.textContent = row.query;
    } else {
      const em = document.createElement("span");
      em.className = "v-null";
      em.textContent = "（空 · 按类型浏览）";
      query.append(em);
    }
    tr.append(query);

    // 筛选条件
    const filters = document.createElement("td");
    filters.className = "col-filters";
    const text = fmtFilters(row.filters);
    if (text) {
      filters.textContent = text;
    } else {
      const em = document.createElement("span");
      em.className = "v-null";
      em.textContent = "—";
      filters.append(em);
    }
    tr.append(filters);

    // 翻到过的最深页 / 每页（不是"当前这一页"）
    const page = document.createElement("td");
    page.className = "col-num";
    page.textContent = row.last_page + " / " + row.size;
    tr.append(page);

    // 命中数。OIRF 的 total 只是词法分支的命中数，加 * 提示别当权威值读
    const total = document.createElement("td");
    total.className = "col-num";
    if (row.result_total === null || row.result_total === undefined) {
      total.textContent = "—";
    } else {
      total.textContent = row.result_total + (row.kind === "oirf" ? " *" : "");
    }
    tr.append(total);

    // 搜过几次。去重丢掉的是时间分布，频次留在这里
    const count = document.createElement("td");
    count.className = "col-num";
    count.textContent = row.search_count + " 次";
    tr.append(count);

    // 重搜
    const go = document.createElement("td");
    go.className = "col-go";
    const a = document.createElement("a");
    a.className = "nav-link";
    a.href = replayUrl(row);
    a.textContent = "重搜";
    go.append(a);
    tr.append(go);

    tbody.append(tr);
  }

  tableEl.hidden = false;
}

/* ---------- 加载 ---------- */

async function loadHistory() {
  const params = new URLSearchParams();
  if (kindSel.value) params.set("kind", kindSel.value);
  params.set("limit", limitSel.value);

  tbody.replaceChildren();
  tableEl.hidden = true;
  showStatus("加载中…");

  let data;
  try {
    const res = await apiFetch("/api/v1/history?" + params.toString());
    if (res.status === 401) return;        // apiFetch 已经在送登录页
    data = await readJson(res);
    if (!res.ok) {
      showStatus("读取失败：" + errorText(data, "HTTP " + res.status), "error");
      return;
    }
  } catch (err) {
    showStatus("请求失败：" + err.message, "error");
    return;
  }

  clearStatus();
  render(data);
}

/* ---------- 事件 ---------- */

kindSel.addEventListener("change", loadHistory);
limitSel.addEventListener("change", loadHistory);
reloadBtn.addEventListener("click", loadHistory);

/* ---------- 初始化 ---------- */

if (requireLogin()) {
  mountUser();
  loadHistory();
}
