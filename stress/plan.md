# 搜索接口压测任务书

对象：`POST /api/v1/reports/search` 全链路

本文可直接作为执行会话的任务说明，压测脚本同目录：`stress/stress_search.py`

结果填第 6 节

前提：ES、Kibana、MongoDB、PostgreSQL 17均已由外部启动；`.env` 已就绪。本任务只需起编码服务与 API

## 1. 目标

1. 进程数 × 并发 的吞吐曲线：峰值配置与拐点在哪。
2. 峰值之后的"下一根柱子"是谁——ES 线程池 / PG 连接池 / 编码服务 / CPU，用单变量对照证明，不靠猜。
3. 报告量从现有 5514 篇放大到 10 万级后的退化幅度，以及每请求多次 ES 往返的代价。

## 2. 两条数据线

| 线 | 索引 | 规模 | 测什么 |
| --- | --- | --- | --- |
| A · 接口层 | 生产报告索引 `knowledge_report_index` | 5514 篇 | 进程 / 连接 / 编码服务链路；ES 规模不变，链路结论干净 |
| B · ES 层 | 同构报告索引 `knowledge_report_stress` | 10 万级 | ES 真实能力 + 应用层叠加开销 |

B 线用同一份 `mapping/report_mapping.json` 建索引，字段与分析器与生产一致，测完即删。

## 3. 口径与规矩

1. 一次只动一个变量，改完重启服务再测。
2. 每档先热身 20 请求，不计入统计。
3. 每档 200 请求、脚本 `--mode mixed`，报 p50 / p95 / p99。
4. 错误分开统计：HTTP 非 200 与客户端异常按类型分开。
5. 每档核对服务端：`search_log` 新增行数 == 发出请求数，`sum(search_count)` 对得上。
6. 结果落 JSON，写到 `/stress`，不依赖终端回读。
7. 中止条件：错误率 > 1%，或出现 > 10 秒的挂起；先定位再继续。
8. 每阶段清 `stress1` 的数据，绝不触碰 `123456`。
9. **读数注意**：Windows stealth mode 下连没监听的端口要等 ~2 秒才报错，"停服务后"的失败延迟含这 2 秒。

## 4. 阶段

**P0 准备**：

- `stress/stress_search.py` 已就位
- `stress/make_reports_stress.py` 已就位
- 冒烟一次、确认索引规模与分片、记空闲基线。

**P1 · A 线拐点矩阵**：

- `WEB_WORKERS` 1/2/4/8 × 并发 8/20/40/80，16 档 × 200 请求
- 要回答：单进程撑多少、8 进程还线不线性、从哪个并发开始塌

**P2 · A 线瓶颈对照**：

- 在 P1 峰值配置下做单变量对照，吞吐提升 > 15% 才算真瓶颈
- E1 `ES_SEARCH_WORKERS`：默认 → 25
- E2 `PG_POOL_MAX` 10 → 20
- E3 编码服务实例数 1 → 2
- E4 `WEB_WORKERS` 4 → 8
- 顺序不代表嫌疑大小，一律让数据说话

**P3 · B 线大数据索引**：

- 造数：`stress/make_reports_stress.py --count 100000 --recreate`；自检 `--stats`、样本 `--dry-run`
- 沿用生产 mapping 与向量口径：`report = title + summary`、同一模型与 `embed_*` 字段；直接 bulk 进索引，不落大文件
- 压测索引默认 3 分片 0 副本，生产 mapping 一个字不改
- 绕过应用直接查该索引，拿该规模的 QPS / 延迟天花板
- 同口径走接口，差值即应用自身开销
- 对比多次 ES 往返在 5514 篇与 10 万级下的代价

**P4 耐久**：

- 并发 = 峰值 × 70%，长跑 15–30 分钟
- 每 30 秒采样内存 RSS / 连接数 / fd / ES queue / 延迟漂移
- 判据：延迟波动 ±20% 内、无错误、无单调上升趋势

**P5 故障与边界**：

- ES 停一个节点
- PG 连接池打满
- 深翻页与非法参数并发

**P6 定稿**：

- 选定默认配置写回 `.env.example` 与 `README.md`
- 结果表贴进 README
- 清理测试数据、提交

## 5. 命令与变量

```powershell
python -m embedding.server                    # 编码服务 127.0.0.1:8020
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH=(Get-Location).Path
$env:ENCODER_URL='http://127.0.0.1:8020'; python run.py    # API 127.0.0.1:8000
python stress/stress_search.py --requests 20 --concurrency 4 --warmup 5 --json   # 冒烟
python stress/stress_search.py --requests 200 --concurrency 40 --mode mixed --json
python stress/stress_search.py --soak 15 --concurrency 40 --json    # 耐久
python stress/make_reports_stress.py --stats 20000                 # 真实 vs 生成分布自检
python stress/make_reports_stress.py --count 100000 --recreate      # B 线造数，先 --dry-run 看样本
# 报告索引为空时先灌生产数据 5514 篇：python scripts/ingest_reports.py
```

压测账号由脚本自建：`stress1` / `stresspass123`，无需手工准备。

| 环境变量 | 默认 | 含义 |
| --- | --- | --- |
| `WEB_WORKERS` | 4 | API 进程数 |
| `PG_POOL_MAX` | 10 | 每进程 PG 连接池上限 |
| `ES_SEARCH_WORKERS` | 自适应 | 每进程 ES 搜索连接数，不设 = `25 / WEB_WORKERS` |
| `ENCODER_URL` | 空 | 空则用进程内模型 |
| `ENCODER_MAX_BATCH` | 32 | 编码服务单批上限 |
| `ENCODER_BATCH_WAIT_MS` | 5 | 合批等待窗口 |

## 6. 结果记录

### A 线拐点矩阵

每格填 `吞吐 req/s` / `p95 ms`

| `WEB_WORKERS` \ 并发 | 8 | 20 | 40 | 80 |
| --- | --- | --- | --- | --- |
| 1 | | | | |
| 2 | | | | |
| 4 | | | | |
| 8 | | | | |

每档另记：p50 / p99、错误分类、服务端核对、run id

### A 线瓶颈对照

| 实验 | 改动 | 吞吐 | 对比基线 | 结论 |
| --- | --- | --- | --- | --- |
| 基线 | — | | | |
| E1 | `ES_SEARCH_WORKERS` 25 | | | |
| E2 | `PG_POOL_MAX` 20 | | | |
| E3 | 编码服务 ×2 | | | |
| E4 | `WEB_WORKERS` 8 | | | |

### B 线大数据索引

| 报告数 | 层级 | 并发 | 吞吐 | p50 | p95 | ES queue | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5514 | 应用接口 | | | | | | A 线基线 |
| 10 w | ES 裸查询 | | | | | | |
| 10 w | 应用接口 | | | | | | |

### P4 耐久

| 配置 | 时长 | 起始内存 | 结束内存 | 起始延迟 | 结束延迟 | 错误 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

## 7. 清理

```sql
DELETE FROM search_history WHERE user_id = (SELECT id FROM users WHERE username = 'stress1');
DELETE FROM search_log     WHERE user_id = (SELECT id FROM users WHERE username = 'stress1');
DELETE FROM users          WHERE username = 'stress1';
```

`search_log.user_id` 无外键、不会级联，须按上序手工删。压测索引：`DELETE /knowledge_report_stress`