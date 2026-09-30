/* OIRF 检索页面
 *
 * 用到的接口：
 *   POST /api/v1/search                               词法 + 向量 RRF 融合
 *                                                     → {total, page, size, hits}
 *   GET  /api/v1/objects/{type}/{oirf_id}?project_id  取对象全文（来自 MongoDB）
 *
 * 和报告页的区别：
 *   - 这个接口返回 total，但它是**词法分支**的命中数（service.py 里只累加
 *     LEXICAL 那一路），不含向量分支。所以 total 可能小于返回条数，极端情况下
 *     total=0 而仍有 20 条结果（词法没匹配上、向量匹配上了）。
 *     因此下面的翻页仍然按「这一页装满了没有」判断，不拿 total 算总页数。
 *   - 后端 RESULT_WINDOW = 200，page * size 超过 200 会 400，
 *     所以 size=20 时最多只能翻到第 10 页
 *   - q 可以留空（变成「按类型浏览」），报告检索则必须给 q
 *
 * 列表里每条（card）的字段：
 *   id, object_type, project_id, oirf_id,
 *   score(RRF 融合分), raw_score(BM25), knn_score(向量), match_source,
 *   identity{name,object_type,status}, presentation{...}, experience{...},
 *   reasoning{...}, responsibility[...], highlight{字段: [片段]}
 *   —— 三种类型的 presentation / experience 内容不一样，下面按类型分别取。
 */

const SEARCH_URL = "/api/v1/search";
const OBJECT_URL = (type, oirfId, projectId) =>
  "/api/v1/objects/" + encodeURIComponent(type) + "/" + encodeURIComponent(oirfId) +
  "?project_id=" + encodeURIComponent(projectId);

const PAGE_SIZE = 20;
const RESULT_WINDOW = 200;                                // 后端上限：page * size <= 200
const MAX_PAGE = Math.floor(RESULT_WINDOW / PAGE_SIZE);   // size=20 → 10

const $ = (id) => document.getElementById(id);

const form = $("searchForm");
const qInput = $("q");
const typeSel = $("type");
const modeSel = $("mode");
const resultsEl = $("results");
const statusEl = $("listStatus");
const detailEl = $("detail");
const pagerEl = $("pager");
const prevBtn = $("prevPage");
const nextBtn = $("nextPage");
const pageInfoEl = $("pageInfo");
const listPane = document.querySelector(".list-pane");

let hits = [];       // 当前这一页
let total = 0;       // 命中总数（接口给的）
let page = 1;
let current = null;  // 当前选中的 oirf_id
let seq = 0;
let detailSeq = 0;

/* ---------- 小工具 ---------- */

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* 字段值形状不统一（字符串 / 数字 / 数组 / {text:...} / {name:...}），
   取值时统一压成一行文字，取不到就返回空串。 */
function text(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(text).filter(Boolean).join("、");
  if (typeof value === "object") {
    for (const k of ["text", "name", "value", "label", "title"]) {
      if (value[k] !== null && value[k] !== undefined) return text(value[k]);
    }
  }
  return "";
}

/* ES 高亮片段里带了 <em> 标签，是希望被当成斜体显示的；
   但片段本身是数据，必须先转义，再把 <em> 还原回去。 */
function highlight(html) {
  return esc(html).replace(/&lt;em&gt;/g, "<em>").replace(/&lt;\/em&gt;/g, "</em>");
}

function titleOf(h) {
  const name = (h.identity && h.identity.name) || h.oirf_id || "无名称";
  const frag = h.highlight && (h.highlight["identity.name"] || [])[0];
  return frag ? highlight(frag) : esc(name);
}

/* 按类型挑几条最能说明「这是什么」的字段，拼成一行。 */
function summaryOf(h) {
  const p = h.presentation || {};
  const e = h.experience || {};
  let pairs;

  if (h.object_type === "source") {
    pairs = [
      ["标题", text(p.title)],
      ["类型", text(p.type)],
      ["发布方", text(p.publisher)],
    ];
  } else if (h.object_type === "evidence") {
    const num = (text(p.value) || text(p.unit)) ? text(p.value) + text(p.unit) : "";
    pairs = [
      ["指标", [text(p.subject), text(p.indicator)].filter(Boolean).join(" · ")],
      ["数值", num],
      ["期间", text(p.period)],
      ["地区", text(p.region)],
    ];
  } else {
    pairs = [
      ["对象", text(p.name)],
      ["情景", text(e.applicable_scenario)],
      ["主张", text(e.claim_type)],
    ];
  }

  return pairs.filter(([, v]) => v).map(([k, v]) => k + " " + v).join("　·　");
}

function showStatus(msg, kind) {
  statusEl.textContent = msg;
  statusEl.className = "status" + (kind ? " " + kind : "");
  statusEl.hidden = false;
}

function clearStatus() {
  statusEl.hidden = true;
  statusEl.textContent = "";
}

/* ---------- 检索 ---------- */

async function doSearch(targetPage = 1) {
  const q = qInput.value.trim();
  const mySeq = ++seq;

  pagerEl.hidden = true;
  showStatus("检索中…");

  // q 留空是合法的：接口会退化成「按类型浏览」
  const body = {
    type: typeSel.value,
    mode: modeSel.value,
    page: targetPage,
    size: PAGE_SIZE,
  };
  if (q) body.q = q;

  let data;
  try {
    // apiFetch（auth.js）= fetch + Authorization 头 + 401 自动跳登录页
    const res = await apiFetch(SEARCH_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (mySeq !== seq) return;
    data = await readJson(res);
    if (mySeq !== seq) return;

    if (res.status === 401) return;   // apiFetch 正在跳登录页，别在这里报错
    if (!res.ok) {
      showStatus("检索失败：" + errorText(data, "HTTP " + res.status), "error");
      return;
    }
  } catch (err) {
    if (mySeq !== seq) return;
    showStatus("请求失败：" + err.message, "error");
    return;
  }

  hits = data.hits || [];
  total = data.total || 0;
  page = targetPage;

  if (hits.length === 0) {
    resultsEl.innerHTML = "";
    if (page > 1) {
      // 翻到空页了，留着翻页条让用户能翻回去
      pagerEl.hidden = false;
      prevBtn.disabled = false;
      nextBtn.disabled = true;
      pageInfoEl.textContent = "第 " + page + " 页 · 没有内容了";
      showStatus("这一页没有内容了", "warn");
    } else {
      pagerEl.hidden = true;
      showStatus("没有匹配的对象，换个说法或换种类型试试", "warn");
    }
    return;
  }

  clearStatus();
  renderList();
  renderPager();
}

/* ---------- 渲染：左栏 ---------- */

// 序号 = (page-1)*PAGE_SIZE + i + 1，接着上一页往下数，不是每页都从 1 开始
function renderList() {
  resultsEl.innerHTML = hits.map((h, i) => {
    const meta = [
      h.object_type ? `<span class="badge">${esc(h.object_type)}</span>` : "",
      h.identity && h.identity.status ? `<span>${esc(h.identity.status)}</span>` : "",
      typeof h.score === "number" ? `<span class="score">融合 ${h.score.toFixed(4)}</span>` : "",
      typeof h.raw_score === "number" ? `<span>BM25 ${h.raw_score.toFixed(1)}</span>` : "",
      typeof h.knn_score === "number" ? `<span>向量 ${h.knn_score.toFixed(3)}</span>` : "",
      h.match_source ? `<span>${esc(h.match_source)}</span>` : "",
    ].join("");

    const summary = summaryOf(h);

    return `
      <li class="card${h.oirf_id === current ? " selected" : ""}" data-id="${esc(h.oirf_id)}">
        <div class="card-top">
          <span class="idx">${(page - 1) * PAGE_SIZE + i + 1}</span>
          <span class="title">${titleOf(h)}</span>
        </div>
        <div class="meta">${meta}</div>
        ${summary ? `<div class="industry">${esc(summary)}</div>` : ""}
      </li>`;
  }).join("");
}

/* 翻页条。
   不用 total 算总页数（它只是词法命中数），只看「这一页装满了没有」。
   total 仍然显示出来，标成「词法命中」，避免被误当成总结果数。 */
function renderPager() {
  const hasPrev = page > 1;
  const atCeiling = page >= MAX_PAGE && hits.length === PAGE_SIZE;
  const hasNext = hits.length === PAGE_SIZE && !atCeiling;

  pagerEl.hidden = false;
  prevBtn.disabled = !hasPrev;
  nextBtn.disabled = !hasNext;
  pageInfoEl.textContent = atCeiling
    ? "第 " + page + " 页 · 已到服务端 " + RESULT_WINDOW + " 条上限"
    : "第 " + page + " 页 · 词法命中 " + total + " 条";
}

function goToPage(target) {
  if (target < 1 || target > MAX_PAGE) return;
  listPane.scrollTop = 0;
  doSearch(target);
}

/* ---------- 渲染：右栏 ---------- */

/* 把对象渲染成一棵缩进的字段树。
   对象的层数不固定（responsibility 里还嵌着 changes），
   所以用递归，不写死任何字段名。 */
function renderValue(v) {
  if (v === null || v === undefined) return `<span class="v-null">—</span>`;

  if (typeof v !== "object") return `<span class="v-scalar">${esc(String(v))}</span>`;

  if (Array.isArray(v)) {
    if (v.length === 0) return `<span class="v-null">[]</span>`;
    return `<div class="v-list">${v.map((x, i) =>
      `<div class="v-item"><span class="v-idx">${i + 1}</span>${renderValue(x)}</div>`
    ).join("")}</div>`;
  }

  const keys = Object.keys(v);
  if (keys.length === 0) return `<span class="v-null">{}</span>`;

  return `<div class="v-obj">${keys.map((k) =>
    `<div class="v-kv"><div class="v-key">${esc(k)}</div>` +
    `<div class="v-val">${renderValue(v[k])}</div></div>`
  ).join("")}</div>`;
}

function badgesOf(obj, extra) {
  return [
    obj.object_type || extra.object_type
      ? `<span class="badge">${esc(obj.object_type || extra.object_type)}</span>` : "",
    obj.identity && obj.identity.status
      ? `<span class="badge">${esc(obj.identity.status)}</span>` : "",
    obj.oirf_id || extra.oirf_id ? `<span>${esc(obj.oirf_id || extra.oirf_id)}</span>` : "",
    obj.project_id != null || extra.project_id != null
      ? `<span>项目 ${esc(obj.project_id ?? extra.project_id)}</span>` : "",
  ].join("");
}

// 点下去的瞬间先画出来（数据列表里已经有了），不用等接口
function renderCard(h, opt = {}) {
  const name = (h.identity && h.identity.name) || h.oirf_id || "无名称";
  const summary = summaryOf(h);
  const note = opt.loading
    ? `<div class="summary pending">正在读取对象全文…</div>`
    : `<div class="summary pending err">${esc(opt.error || "")}</div>`;

  detailEl.innerHTML = `
    <h2 class="d-title">${esc(name)}</h2>
    <div class="meta">${badgesOf(h.identity || {}, h)}</div>
    ${summary ? `<div class="industry">${esc(summary)}</div>` : ""}
    ${note}`;
}

function renderObject(obj, extra) {
  const name = text(obj.identity && obj.identity.name) || extra.oirf_id || "无名称";
  detailEl.innerHTML = `
    <h2 class="d-title">${esc(name)}</h2>
    <div class="meta">${badgesOf(obj, extra)}</div>
    <div class="tree">${renderValue(obj)}</div>`;
}

/* ---------- 读对象全文 ---------- */

async function loadDetail(hit) {
  const mySeq = ++detailSeq;
  renderCard(hit, { loading: true });

  // 接口要求 project_id 才能定位（oirf_id 只在项目内唯一）
  if (hit.project_id === null || hit.project_id === undefined) {
    renderCard(hit, { error: "这条没有 project_id，取不到对象全文" });
    return;
  }

  let data;
  try {
    const res = await apiFetch(OBJECT_URL(hit.object_type, hit.oirf_id, hit.project_id));
    if (mySeq !== detailSeq) return;
    data = await readJson(res);
    if (mySeq !== detailSeq) return;

    if (res.status === 401) return;   // apiFetch 正在跳登录页
    if (!res.ok) {
      renderCard(hit, { error: "取对象失败：" + errorText(data, "HTTP " + res.status) });
      return;
    }
  } catch (err) {
    if (mySeq !== detailSeq) return;
    renderCard(hit, { error: "请求失败：" + err.message });
    return;
  }

  renderObject(data, hit);
}

function resetDetail() {
  current = null;
  detailSeq++;
  detailEl.innerHTML = `<p class="placeholder">在左侧点一条，这里显示对象全文。</p>`;
}

/* ---------- 事件 ---------- */

form.addEventListener("submit", (e) => {
  e.preventDefault();
  resetDetail();
  doSearch(1);
});

typeSel.addEventListener("change", () => {
  resetDetail();
  doSearch(1);
});

modeSel.addEventListener("change", () => {
  resetDetail();
  doSearch(1);
});

prevBtn.addEventListener("click", () => goToPage(page - 1));
nextBtn.addEventListener("click", () => goToPage(page + 1));

resultsEl.addEventListener("click", (e) => {
  const li = e.target.closest("li.card");
  if (!li) return;
  const hit = hits.find((h) => h.oirf_id === li.dataset.id);
  if (!hit) return;

  current = hit.oirf_id;
  renderList();
  loadDetail(hit);
});

/* ---------- 初始化 ---------- */

/* 从 URL 预填表单：搜索记录页的「重搜」链接会带 q / type / mode / go。
 * 认不出来的值（比如手改 URL 塞 type=foo）一律退回默认 —— 让它进到请求里
 * 只会被后端 422 打回来。 */
function applyUrlParams() {
  const p = new URLSearchParams(location.search);

  const q = p.get("q");
  if (q !== null) qInput.value = q;

  const type = p.get("type");
  if (type && Array.from(typeSel.options).some((o) => o.value === type)) {
    typeSel.value = type;
  }

  const mode = p.get("mode");
  if (mode && Array.from(modeSel.options).some((o) => o.value === mode)) {
    modeSel.value = mode;
  }

  return p.get("go") === "1";
}

// 没登录就跳登录页，后面的初始化不做（requireLogin 已经在跳了）
if (requireLogin()) {
  mountUser();
  if (applyUrlParams()) doSearch(1);   // go=1 才自动开搜，否则只预填
  qInput.focus();
}
