# 更新日志

## 未发布

相对 `origin/main`（`041ed14`）：

### 2026-09-23 · 登录与检索记录

- 注册与登录：账号存 PostgreSQL，密码存 Argon2id 哈希，登录签发 HS256 的 JWT。主体按照 FastAPI 教程 Security 实现
- 新增登录 / 注册页 `/ui/login.html`
- 除 `/health`、`/health/ready`、`/auth/register`、`/auth/token` 外，检索相关接口一律带上 `Authorization: Bearer`
- 建表 `schema/auth.sql` + `scripts/init_pg.py`；PostgreSQL 内存储用户信息、历史检索记录、检索日志三张表
- 检索记录查询 `GET /api/v1/history`，一行 = 一次检索，翻页合并；另有页面 `/ui/history.html` 可查询检索记录
- 请求日志 `search_log`，一行 = 一次请求，成功失败都记，目前只存入库中不读取

### 2026-09-28 · 编码服务、并发配置与压测资产

- 编码从 API 进程拆出：新增独立编码服务 `embedding/server.py`，单进程单模型、query 合批；`app/search/encoder.py` 改为入口，`ENCODER_URL` 有值走远端客户端，否则用进程内模型，带熔断与降级
- 检索响应新增 `degraded`，编码不可用时只走词法
- `/api/v1/health/ready` 增加 `encoder` 字段
- 新增并发参数 `WEB_WORKERS` / `PG_POOL_MAX` / `ES_SEARCH_WORKERS`，`app/config.py` 导入时校验
- `app/main.py` 压掉 httpx 的 INFO 日志，检索词不再进日志
- 新增压测任务书 `stress/archive/plan.md`、压测脚本 `stress/archive/stress_search.py`、造数脚本 `stress/archive/make_reports_stress.py`

### 2026-09-29 · 多实例与压测结果

- API 改多实例：`serve.py` 起 `WEB_WORKERS` 个单进程实例，套一个本地转发层负责轮询与故障摘除，对外仍是 `127.0.0.1:8000`；`run.py` 变薄壳，`--instances 1` 同样走转发层
- 单次检索给 ES 的时间改用 `ES_REQUEST_TIMEOUT`，默认 10 秒
- 新增 `stress/archive/report.md` 与结果归档 `stress/archive/stress-results-20260929.zip`，压测结论见 [stress/archive/report.md](stress/archive/report.md)

### 2026-09-30 · 整体容器化

- API、PostgreSQL、独立编码服务进容器，与原有 ES / Kibana / Mongo 合成一套 compose，删掉转发层
- 新增 `docker/app.Dockerfile`和 `.dockerignore`；API 镜像的依赖靠 `requirements.txt` 的 `encoder-only` 标记过滤；编码服务走 GPU
- 配置收敛：端口一律绑回环，`COMPOSE_PROJECT_NAME` 钉死 `98`，空数据目录上建集群改由 `.env` 的 `ES_INITIAL_MASTER_NODES` 控制

### 2026-10-08 · 排序窗口与翻页取数 & 压测资产更替

- 两路召回只取排序窗口的排名；融合选出当页后再按 `_id` 取回该页的 `_source` 与高亮
- 单请求 ES 开销从 47 ms / 259 KB 降到 16 ms / 29 KB，高亮结果不变
- 新增 `RANK_BUFFER` 控制排序窗口大小，`0` = 默认 读满 200 条
- 删去原先的压测脚本与结果
- 新增服务端压力测试报告 `stress/report-p3.md`：并发 120→8192，成功吞吐天花板 119–197 req/s，七个容器无 OOM、无退出、无重启

### 2026-10-09 · 单请求固定开销

- PG 借连接加 2 秒超时，连接池打满时快速失败，不再把请求挂满 30 秒
- 单次检索给 ES 的时间改为单次尝试，最多重试 1 次，超时不重试
- kNN 召回倍数从 5 改回 2，5 是压测时的遗留值

### 2026-10-13 · 后台写、用户缓存与连接复用

- 检索日志与检索历史改到响应发出后写入，不再占用请求耗时
- 用户查表加 5 秒缓存，注册、改密、禁用时立即失效
- API 空闲连接超时从 5 秒改为 60 秒，新增 `KEEPALIVE_TIMEOUT`
- 新增复跑报告 `stress/report-p3-repro.md` 与 `stress/report-p3-rerun.md`：三档吞吐均高于原报告，8192 档的连接建立失败未复现，keep-alive 改为 60 秒后失败全部归零
- 压测脚本与结果归档，只留报告

### 2026-10-14 · 监听队列与内存定位

- 定位 `ConnectError`，解决方案为 API 监听队列抬到 8192
- 定位 api 内存增长：非每请求泄漏，是 glibc 分配器与线程栈的高水位
