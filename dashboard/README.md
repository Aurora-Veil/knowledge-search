# Dashboard

knowledge-search 的新前端，React 19 + Vite + React Router。

`static/` 里是构建后的产物，此处为源码。

## 开发步骤

先启动 FastAPI（监听 `http://127.0.0.1:8000`），再：

```bash
cd dashboard
pnpm dev
```

打开 `http://127.0.0.1:5173/ui/`。

开发时 Vite 把 `/api`、`/mcp`、`/docs`、`/openapi.json` 代理到 8000，
前端代码里直接请求 `/api/v1/...`，不用写完整域名。

前端没有 mock 后端，登录、报告检索、历史记录、概览统计都走真实接口。
没有后端时页面只能停在登录页。

## 构建与部署

```bash
cd dashboard
pnpm build
```

产物在 `dashboard/dist/`，只有 `index.html` 和带哈希的 `assets/`。

部署到 FastAPI 的 `/ui/`：

```bash
rm -rf static/*
cp -r dashboard/dist/* static/

# 重建镜像
docker compose up -d --build api
```

打开 `http://127.0.0.1:8000/ui/`。

前端用 `HashRouter`，页面地址是 `#/report`、`#/history` 这种形式；
`/ui/report` 不是 SPA fallback，刷新会 404。

## 结构

```text
src/
  main.jsx          入口
  App.jsx           路由
  styles/           全局样式
  components/       通用组件
  auth/             登录状态
  lib/              接口封装
  features/
    report/         报告检索
    overview/       概览图表
  pages/            页面
```
