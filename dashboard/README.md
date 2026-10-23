# dashboard

knowledge-search 的新前端，React 19 + Vite + React Router。

## 启动

```bash
cd dashboard
npm run dev
```

打开 http://127.0.0.1:5173/ui/ 。地址里的 `/ui/` 不能省，因为 Vite 配了 `base: '/ui/'`，和线上挂在 FastAPI 下的路径保持一致。

## 后端

开发时 Vite 把 `/api` 代理到 `http://127.0.0.1:8000`，所以先启动 FastAPI：

```bash
python -m app.main
```

前端代码里直接请求 `/api/v1/...` 即可，不用写完整域名。

## 假后端（默认开启）

`npm run dev` 时会自动挂两个只存在于开发环境的假后端，代码在 `mock/` 下，`apply: 'serve'` 保证打包不会带进 `dist/`：

| 文件 | 挡住的路径 |
|---|---|
| `mock/dev-auth.js` | `/api/v1/auth/*`：登录、注册、当前用户 |
| `mock/dev-reports.js` | `POST /api/v1/reports/search`、`GET /api/v1/reports/{id}` |

报告接口的形状照 `app/routers/reports.py` 抄：参数名是 `q` / `layout` / `mode` / `page` / `size` / `time_weight` / `publish_date_from` / `publish_date_to`，返回 `{ total, page, size, degraded, hits }`，`hits` 里**没有** `summary`，摘要要走详情接口。错误码也对齐：空 `q` 422、`page*size > 200` 400、没通行证 401、详情不存在 404。

所以页面代码里没有一行“因为没后端所以先这样”的分支，真后端起来直接能用。

登录账号：

| 账号 | 密码 | 结果 |
|---|---|---|
| `demo` | `demo1234` | 登录成功 |
| `disabled` | `disabled1234` | 403 账号已停用 |
| 其他 | 任意 | 401 用户名或密码不对 |

注册：用户名重复返回 409，密码少于 8 位返回 422。

两个假后端共用一个开关，必须同时开或同时关，否则会出现“能登录但搜不了”。真后端起来后：

```powershell
$env:MOCK_API=0
npm run dev
```

注意 mock 的用户和通行证只存在内存里，重启 dev server 后登录状态会失效，需要重新登录。


## 构建

```bash
npm run build
```

产物在 `dist/`。验收通过后再把 `dist/` 的内容复制到仓库的 `static/`。

## 结构

```text
src/
  main.jsx              入口，按顺序引入样式
  App.jsx               路由表
  styles/
    tokens.css          颜色、圆角、字号
    base.css            重置、输入框、按钮
    shell.css           侧栏 + 顶栏 + 内容区
    pages.css           概览、登录、占位页
    report.css          报告检索页
  components/
    AppShell.jsx        布局路由，套住除登录外的所有页面
    Sidebar.jsx  Topbar.jsx  Pager.jsx
  auth/AuthContext.jsx  登录状态、登录 / 注册 / 退出
  lib/
    api.js              fetch 封装：自动带通行证，401 统一处理
    auth.js             通行证的读写
    reports.js          报告接口：searchReports、getReport、listHistory
  features/report/      报告页
    SearchCard.jsx      搜索卡（受控组件）
    ResultList.jsx  ResultItem.jsx  结果列表
    ReportDetail.jsx    详情（摘要来自单独的接口）
    searchParams.js     UI 选项 → 请求体，含“近一年”到日期的换算
    format.js           分值与命中来源的展示文案
    highlight.js        高亮：切分后端的 <em> 串、给没走接口的字段补标、判断标签是否命中
    HighlightText.jsx   渲染片段，命中词包 <mark class="hl">
  pages/                概览、登录、OIRF、搜索记录（HistoryPage 已接接口）
  mock/data.js          假数据，字段名和接口一致
mock/
  dev-auth.js           假登录 / 注册 / me
  dev-reports.js        假检索 / 详情，检索成功时顺手调 recordSearch
  dev-history.js        假搜索记录，内存里攒；重启 vite 清空
```

## 当前进度

- 登录、注册、退出：已接 `apiFetch`，401 会自动踢回登录页
- 报告检索：已接真实接口。搜索卡受控，列表和详情分两次请求，翻页可用
- 高亮：标题、列表摘要用后端 `highlight`；行业标签和详情标题/摘要用检索词在前端补标
- 搜索记录：已接 `GET /api/v1/history`，类型/条数筛选、相对时间、空结果数显示 `—`
- 概览、OIRF：仍然是静态数据
- 图表暂时不做，等后端给出聚合数据再加

