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

### 2026-10-15 · 报告检索结果缓存

- `POST /api/v1/reports/search` 的响应体进 Redis：命中时零次 ES 往返，也不再调编码服务
- 键是规范化参数的 sha256；过期时刻固定为下一个午夜，不设固定 TTL，因此命中的必然是当天写入的
- Redis 侧任何异常都当未命中回落 ES，不向调用方报错，也不并入 `/health/ready` 的 503 判定
- `/api/v1/health/ready` 新增 `cache` 段：`enabled` / `reachable` / `errors` / `keys`
- 新增 `ENABLE_REPORT_CACHE`，默认开；`REDIS_URL` 留空同样停用
- 分页越界与非法 `mode` 的校验提前到查缓存之前，非法请求仍是 400

### 2026-10-19 · 缓存开关注入、扩容 & query 向量缓存 & 测试脚本改造与结果

- redis `maxmemory` 256 MB → 512 MB，`mem_limit` 384m → 768m，键容量约 15.7k → 31.5k
- 检索 q 的向量存 PostgreSQL 表 `query_vec`：命中时不再调编码服务，
- 点查超时或异常一律当未命中，回落编码服务
- 新增 `schema/query_vec.sql`，在 compose 里挂成 pg 的 initdb 脚本；api 服务注入 `QUERY_VEC_ENABLED`，默认开
- 新增 `scripts/backfill_query_vec.py`：近 30 天去重查询词向量化入库作为缓存
- 更新压测脚本，增加更多 query 种类与过滤的查询请求，模拟真实用户查询与翻页
- 新增压测报告 [stress/reports/report-mid-ladder.md](stress/reports/report-mid-ladder.md)，包含固定redis缓存下不同并发的 req/s 与缓存全命中时的理想数据

### 2026-10-23 · 前端换 React

- 前端重写为独立工程 `dashboard/`：Vite + React 19，不引 UI 库，dev 与生产都挂在 `/ui/` 下
- 目前完成内容为：报告检索页，含检索卡、列表、详情、翻页与高亮；搜索记录页接 `GET /api/v1/history`；错误边界；开发期假后端；旧 `static/` 停止追踪
- 待办内容为：概览页接历史接口、真实后端联调、图表（等后端聚合数据）、`/ui` 挂载点切到构建产物

### 2026-10-26 · 概览统计接口 & 用户相关界面

- 新增 `GET /api/v1/stats/report-library`、`GET /api/v1/stats/search-activity`：用于提供前端集成图表的统计数据
- MCP 新增 `report_stats`、`search_stats`，只有全站口径，不带用户维度
- 修 `search_count` 口径，保证不将翻页视为新的查询
- 报告检索页布局优化，加入当前页检索结果的行业标签数量显示
- 用户相关：侧栏加入用户菜单：头像、账号状态、设置入口、退出登录，用户菜单带 MCP 状态检测；新增 `/settings` 页，显示用户 ID、状态与注册时间

### 2026-10-27 · 检索统计与概览页

- 新增 `search_daily` 日汇总表和 `app/searchlog/rollup.py`，从 `search_log` 汇总 `page=1` 的请求，支持单日、区间、最近 N 天与全量回填
- `/api/v1/stats/search-activity` 改为只读 `search_daily`，去掉 `scope`；响应增加 `data_until`、`zero_result`、`errors`、`latency_sum`、`ok_count`
- 两个统计接口的结果写入 Redis：报告库 10 分钟，检索行为按区间缓存 24 小时或 60 秒
- 报告库统计增加每年行业分布和 `industry_years` 逐年数量，缓存键升为 `stats:reports:v2`
- MCP `search_stats` 同步新口径，数据截至昨天
- 概览页用 ECharts 接入真实统计图表，图表支持联动筛选
- 检索记录中的报告检索词可回填筛选条件并重新检索
- `/ui/` 改为只提供 React 构建产物，旧手写静态页面删除；开发期 mock 后端移除，开发需连接真实 FastAPI
- Vite 增加 `/docs` 与 `/openapi.json` 代理；登录页移除“回到概览”
- 重构文档：重写 README、`dashboard/README.md` 与搜索 API 文档，新增概览统计 API 文档
