/* 报告检索页面 —— 第①②③步：检索 + 左栏列表 + 右栏详情 + 翻页
 *
 * 用到的接口：
 *   POST /api/v1/reports/search   语义检索，返回 {"hits": [...]}，没有 total
 *   GET  /api/v1/reports/{id}     单条详情，比列表多一个 summary
 *
 * 列表接口返回的每条字段：
 *   report_id, title, industry[], layout, publish_date, url, score
 */

const SEARCH_URL = "/api/v1/reports/search";
// 详情接口：GET /api/v1/reports/{report_id}
const DETAIL_URL = (id) => "/api/v1/reports/" + encodeURIComponent(id);
const PAGE_SIZE = 20;
// 后端限制 page * size <= 10000（MAX_RESULT_WINDOW），超了返回 400。
// 没有 total 就算不出总页数，只能自己按这个上限掐住。
const MAX_PAGE = Math.floor(10000 / PAGE_SIZE);

// 把 id 转成元素。写起来短，读起来也清楚。
const $ = (id) => document.getElementById(id);

const form = $("searchForm");
const qInput = $("q");
const layoutSel = $("layout");
const resultsEl = $("results");
const statusEl = $("listStatus");
const detailEl = $("detail");
const pagerEl = $("pager");
const prevBtn = $("prevPage");
const nextBtn = $("nextPage");
const pageInfoEl = $("pageInfo");
const listPane = document.querySelector(".list-pane");

let hits = [];       // 当前这一页的结果
let page = 1;        // 当前页码
let current = null;  // 当前选中的 report_id
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

// targetPage 默认 1：点搜索、换版式，都从第一页重新开始。
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

  showStatus("检索中…");

  const body = { q: q, page: targetPage, size: PAGE_SIZE };
  if (layoutSel.value) body.layout = layoutSel.value;

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
      pagerEl.hidden = true;
      showStatus("检索失败：" + (data.detail || res.status), "error");
      return;
    }
  } catch (err) {
    if (mySeq !== seq) return;
    pagerEl.hidden = true;
    showStatus("请求失败：" + err.message, "error");
    return;
  }

  hits = data.hits || [];
  page = targetPage;

  if (hits.length === 0) {
    resultsEl.innerHTML = "";
    if (page > 1) {
      // 翻到了空页，翻页条留着，好让用户能往回翻
      renderPager();
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
  resultsEl.innerHTML = hits.map((h, i) => {
    const meta = [
      h.layout ? `<span class="badge">${esc(h.layout)}</span>` : "",
      h.publish_date ? `<span>${esc(h.publish_date)}</span>` : "",
      typeof h.score === "number" ? `<span class="score">${h.score.toFixed(3)}</span>` : "",
    ].join("");

    const industry = (h.industry && h.industry.length)
      ? `<div class="industry">${esc(h.industry.join(" / "))}</div>`
      : "";

    return `
      <li class="card${h.report_id === current ? " selected" : ""}" data-id="${esc(h.report_id)}">
        <div class="card-top">
          <span class="idx">${(page - 1) * PAGE_SIZE + i + 1}</span>
          <span class="title">${esc(h.title) || "无标题"}</span>
        </div>
        <div class="meta">${meta}</div>
        ${industry}
      </li>`;
  }).join("");
}

/* 翻页条。
   列表接口不返回 total，所以显示不出「共 N 页」，
   只能靠「这一页装满了没有」来判断还有没有下一页。 */
function renderPager() {
  const hasPrev = page > 1;
  const hasNext = hits.length === PAGE_SIZE && page < MAX_PAGE;

  if (!hasPrev && !hasNext) {
    pagerEl.hidden = true;   // 只有一页，不用显示翻页条
    return;
  }

  pagerEl.hidden = false;
  prevBtn.disabled = !hasPrev;
  nextBtn.disabled = !hasNext;
  pageInfoEl.textContent = "第 " + page + " 页";
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

// 换了版式就重搜一次，省得再点按钮
layoutSel.addEventListener("change", () => {
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
