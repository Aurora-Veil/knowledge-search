# 更新日志

## 未发布

相对 `main`（`1ef7bff`）：

- 注册与登录：账号存 PostgreSQL，密码存 Argon2id 哈希，登录签发 HS256 的 JWT。主体按照 FastAPI 教程 Security 实现
- 新增登录 / 注册页 `/ui/login.html`
- 除 `/health`、`/health/ready`、`/auth/register`、`/auth/token` 外，检索相关接口一律带上 `Authorization: Bearer`
- 建表 `schema/auth.sql` + `scripts/init_pg.py`；PostgreSQL 内存储用户信息、历史检索记录、检索日志三张表
- 检索记录查询 `GET /api/v1/history`，一行 = 一次检索，翻页合并；另有页面 `/ui/history.html` 可查询检索记录
- 请求日志 `search_log`，一行 = 一次请求，成功失败都记，目前只存入库中不读取
