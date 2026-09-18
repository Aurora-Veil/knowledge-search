/* 报告检索页面 —— 检索 + 左栏列表 + 右栏详情 + 翻页
 *
 * 用到的接口：
 *   POST /api/v1/reports/search   词法 + 向量 RRF 融合 → {total, page, size, hits}
 *   GET  /api/v1/reports/{id}     单条详情，比列表多一个 summary
 *
 * 和 OIRF 页的区别：
 *   - 这个接口返回 total，但它只是**词法分支**的命中数（service_reports.py 里
 *     只累加 LEXICAL 那一路），不含向量分支。所以 total 可能小于返回条数，
 *     极端情况下 total=0 而仍有 20 条结果（词法没匹配上、向量匹配上了）。
 *     因此下面的翻页仍然按「这一页装满了没有」判断，不拿 total 算总页数。
 *   - 后端 RESULT_WINDOW = 200，page * size 超过 200 会 400，
 *     所以 size=20 时最多只能翻到第 10 页
 *   - q 必须给（报告页不做「留空浏览」），mode 只约束词法那一路
 *   - 发布时间下拉映射到 publish_date_from / publish_date_to，默认「全部时间」
 *     就是两个字段都不发；空串会被后端当非法日期挡成 422，所以必须省略
 *   - 时间权重下拉映射到 time_weight，默认「不衰减」= 不发这个字段（后端默认 0）
 *
 * 列表里每条（card）的字段：
 *   report_id, title, industry[], layout, publish_date, url,
 *   score(RRF 融合分), raw_score(BM25), knn_score(向量), match_source,
 *   —— 传了 time_weight 时 raw_score / knn_score 已含时间衰减，标签会写成 ×时间
 *   highlight{字段: [片段]}
 *   —— 摘要只在详情接口返回，列表里没有。
 */

const SEARCH_URL = "/api/v1/reports/search";
// 详情接口：GET /api/v1/reports/{report_id}
const DETAIL_URL = (id) => "/api/v1/reports/" + encodeURIComponent(id);
const PAGE_SIZE = 20;
const RESULT_WINDOW = 200;                                // 后端上限：page * size <= 200
const MAX_PAGE = Math.floor(RESULT_WINDOW / PAGE_SIZE);   // size=20 → 10

// 把 id 转成元素。写起来短，读起来也清楚。
const $ = (id) => document.getElementById(id);

const form = $("searchForm");
const qInput = $("q");
const layoutSel = $("layout");
const modeSel = $("mode");
const periodSel = $("period");
const decaySel = $("decay");
const resultsEl = $("results");
const statusEl = $("listStatus");
const detailEl = $("detail");
const pagerEl = $("pager");
const prevBtn = $("prevPage");
const nextBtn = $("nextPage");
const pageInfoEl = $("pageInfo");
const listPane = document.querySelector(".list-pane");

let hits = [];       // 当前这一页的结果
let total = 0;       // 命中总数（接口给的）
let page = 1;        // 当前页码
let current = null;  // 当前选中的 report_id
let decayW = 0;      // 本次检索用的时间衰减权重，渲染时决定分数标签的口径
let seq = 0;         // 检索的请求序号，见下面 doSearch 里的说明
let detailSeq = 0;   // 详情的请求序号，同理（快速连点两条时防止串台）

/* ---------- 小工具 ---------- */

// 报告标题、分类来自 ES，可能含 & < > " 等字符。
// 直接塞进 innerHTML 会破坏页面结构，所以先转义。
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ES 高亮片段里带了 <em> 标签，是希望被当成斜体显示的；
   但片段本身是数据，必须先转义，再把 <em> 还原回去。 */
function highlight(html) {
  return esc(html).replace(/&lt;em&gt;/g, "<em>").replace(/&lt;\/em&gt;/g, "</em>");
}

// 标题：词法命中时优先用高亮片段，没命中就用原文
function titleOf(h) {
  const frag = h.highlight && (h.highlight.title || [])[0];
  return frag ? highlight(frag) : (esc(h.title) || "无标题");
}

/* 日期只认 YYYY-MM-DD（后端 _date() 校验得很死，别的格式直接 400）。
   这里按本地时间取年月日，不用 toISOString()，否则会被时区挪掉一天。 */
function ymd(d) {
  const p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
}

function yearsAgo(n) {
  const d = new Date();
  d.setFullYear(d.getFullYear() - n);
  return ymd(d);
}

/* 发布时间下拉的值 -> [from, to]，两端都可能为 null（表示这一头不限制）。
   空值 -> 不加过滤；1y/3y/5y -> 今天往前推，只卡下界；2024 -> 那一整个自然年。 */
function periodRange(value) {
  if (!value) return [null, null];
  if (value.endsWith("y")) return [yearsAgo(Number(value.slice(0, -1))), null];
  return [value + "-01-01", value + "-12-31"];
}

function showStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = "status" + (kind ? " " + kind : "");
  statusEl.hidden = false;
}

function clearStatus() {
  statusEl.hidden = true;
  statusEl.textContent = "";
}

/* ---------- 检索 ---------- */

// targetPage 默认 1：点搜索、换版式、换匹配方式，都从第一页重新开始。
async function doSearch(targetPage = 1) {
  const q = qInput.value.trim();
  if (!q) {
    hits = [];
    resultsEl.innerHTML = "";
    pagerEl.hidden = true;
    showStatus("请先输入检索词", "warn");
    return;
  }

  // 每次检索领一个号。等结果回来时如果号已经变了，说明用户又搜了一次，
  // 这次的结果过期了，直接丢掉 —— 否则慢的旧请求会覆盖新结果。
  // （向量检索首次要 10~20 秒，很容易出现这种先后错位。）
  const mySeq = ++seq;

  pagerEl.hidden = true;
  showStatus("检索中…");

  const body = { q: q, mode: modeSel.value, page: targetPage, size: PAGE_SIZE };
  if (layoutSel.value) body.layout = layoutSel.value;

  const [dateFrom, dateTo] = periodRange(periodSel.value);
  if (dateFrom) body.publish_date_from = dateFrom;
  if (dateTo) body.publish_date_to = dateTo;

  decayW = Number(decaySel.value) || 0;
  if (decayW > 0) body.time_weight = decayW;

  let data;
  try {
    const res = await fetch(SEARCH_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (mySeq !== seq) return;
    data = await res.json();
    if (mySeq !== seq) return;

    if (!res.ok) {
      // FastAPI 的报错格式是 {"detail": "..."}
      showStatus("检索失败：" + (data.detail || res.status), "error");
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
      showStatus("没有匹配的报告，换个说法试试", "warn");
    }
    return;
  }

  clearStatus();
  renderList();
  renderPager();
}

/* ---------- 渲染 ---------- */

// 序号 = (page-1)*PAGE_SIZE + i + 1，接着上一页往下数，不是每页都从 1 开始
function renderList() {
  // 开了时间衰减后 raw_score / knn_score 都乘过衰减因子，标签跟着改口径
  const bm25Label = decayW > 0 ? "BM25×时间" : "BM25";
  const knnLabel = decayW > 0 ? "向量×时间" : "向量";

  resultsEl.innerHTML = hits.map((h, i) => {
    const meta = [
      h.layout ? `<span class="badge">${esc(h.layout)}</span>` : "",
      h.publish_date ? `<span>${esc(h.publish_date)}</span>` : "",
      typeof h.score === "number" ? `<span class="score">融合 ${h.score.toFixed(4)}</span>` : "",
      typeof h.raw_score === "number" ? `<span>${bm25Label} ${h.raw_score.toFixed(1)}</span>` : "",
      typeof h.knn_score === "number" ? `<span>${knnLabel} ${h.knn_score.toFixed(3)}</span>` : "",
      h.match_source ? `<span>${esc(h.match_source)}</span>` : "",
    ].join("");

    const industry = (h.industry && h.industry.length)
      ? `<div class="industry">${esc(h.industry.join(" / "))}</div>`
      : "";

    return `
      <li class="card${h.report_id === current ? " selected" : ""}" data-id="${esc(h.report_id)}">
        <div class="card-top">
          <span class="idx">${(page - 1) * PAGE_SIZE + i + 1}</span>
          <span class="title">${titleOf(h)}</span>
        </div>
        <div class="meta">${meta}</div>
        ${industry}
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

function renderDetail(h, opt = {}) {
  const meta = [
    h.layout ? `<span class="badge">${esc(h.layout)}</span>` : "",
    h.publish_date ? `<span>${esc(h.publish_date)}</span>` : "",
    h.report_id ? `<span>${esc(h.report_id)}</span>` : "",
  ].join("");

  const industry = (h.industry && h.industry.length)
    ? `<div class="d-industry">${esc(h.industry.join(" / "))}</div>`
    : "";

  const origin = h.url
    ? `<a class="origin" href="${esc(h.url)}" target="_blank" rel="noopener">查看原文 ↗</a>`
    : "";

  // 摘要只有详情接口才有（列表接口不返回），所以这里分几种情况。
  let summary;
  if (opt.loading) {
    summary = `<div class="summary pending">正在读取摘要…</div>`;
  } else if (opt.error) {
    summary = `<div class="summary pending err">${esc(opt.error)}</div>`;
  } else if (typeof h.summary === "string" && h.summary.trim()) {
    summary = `<div class="summary">${esc(h.summary)}</div>`;
  } else {
    // 索引里有不少报告只有标题没有摘要，别显示成一片空白
    summary = `<div class="summary pending">该报告没有摘要</div>`;
  }

  detailEl.innerHTML = `
    <h2 class="d-title">${esc(h.title) || "无标题"}</h2>
    <div class="meta">${meta}</div>
    ${industry}
    ${summary}
    ${origin}`;
}

function resetDetail() {
  current = null;
  detailSeq++;   // 让还在飞的详情请求作废
  detailEl.innerHTML = `<p class="placeholder">在左侧点一条报告，这里显示详情。</p>`;
}

/* 读一条的详情。
   列表里已经有标题/版式/日期/分类，点下去先把这些显示出来，
   摘要等接口回来再补上 —— 这样点击是立刻有反应的，不会像卡住。 */
async function loadDetail(hit) {
  const mySeq = ++detailSeq;
  renderDetail(hit, { loading: true });

  let data;
  try {
    const res = await fetch(DETAIL_URL(hit.report_id));
    if (mySeq !== detailSeq) return;
    data = await res.json();
    if (mySeq !== detailSeq) return;

    if (!res.ok) {
      renderDetail(hit, { error: "取详情失败：" + (data.detail || res.status) });
      return;
    }
  } catch (err) {
    if (mySeq !== detailSeq) return;
    renderDetail(hit, { error: "请求失败：" + err.message });
    return;
  }

  renderDetail(data);
}

/* ---------- 事件 ---------- */

// 提交表单（点搜索按钮，或在输入框里按回车）
form.addEventListener("submit", (e) => {
  e.preventDefault();   // 阻止浏览器默认的整页刷新
  resetDetail();
  doSearch(1);
});

// 换了版式或匹配方式就重搜一次，省得再点按钮
layoutSel.addEventListener("change", () => {
  if (!qInput.value.trim()) return;
  resetDetail();
  doSearch(1);
});

modeSel.addEventListener("change", () => {
  if (!qInput.value.trim()) return;
  resetDetail();
  doSearch(1);
});

periodSel.addEventListener("change", () => {
  if (!qInput.value.trim()) return;
  resetDetail();
  doSearch(1);
});

decaySel.addEventListener("change", () => {
  if (!qInput.value.trim()) return;
  resetDetail();
  doSearch(1);
});

// 翻页
prevBtn.addEventListener("click", () => goToPage(page - 1));
nextBtn.addEventListener("click", () => goToPage(page + 1));

// 点列表。用「事件委托」：只在父元素上挂一个监听，
// 以后重新渲染列表也不用重新绑事件。
resultsEl.addEventListener("click", (e) => {
  const li = e.target.closest("li.card");
  if (!li) return;
  const hit = hits.find((h) => h.report_id === li.dataset.id);
  if (!hit) return;

  current = hit.report_id;
  renderList();          // 重画一次以更新选中高亮
  loadDetail(hit);
});

qInput.focus();
