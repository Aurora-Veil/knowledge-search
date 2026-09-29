# 搜索接口压测任务书

对象：`POST /api/v1/reports/search` 全链路

执行会话按本文做，脚本同在 `stress/`，结果填第 6 节

前提：ES、Kibana、MongoDB、PostgreSQL 17 均已启动，`.env` 已就绪；只需再起编码服务与 API

## 1. 目标

1. 并发 → 吞吐曲线：峰值并发在哪、从哪一档开始塌。`WEB_WORKERS` 固定 4，不再扫进程数。
2. 报告量从现有 5514 篇放大到 3 万级后的退化幅度，以及每请求多次 ES 往返的代价。

## 2. 两条数据线

| 线 | 索引 | 规模 | 测什么 |
| --- | --- | --- | --- |
| A · 接口层 | 生产报告索引 `knowledge_report_index` | 5514 篇 | 进程 / 连接 / 编码服务链路；ES 规模不变 |
| B · ES 层 | 同构报告索引 `knowledge_report_stress` | 3 万级 | ES 真实能力 + 应用层叠加开销 |

B 线用同一份 `mapping/report_mapping.json` 建索引，测完即删。

B 线原本按 10 万级设计，10 万条编码加 bulk 时间过长。测试结论基于 3 万条数据开始；结论若需要更大规模再加量。

## 3. 口径与规矩

1. 一次只动一个变量；并发只改脚本参数，服务端配置不动的档位不用重启。
2. 每档先热身 20 请求，不计入统计。
3. 每档 200 请求、脚本 `--mode mixed`，报 p50 / p95 / p99。
4. 错误分开统计：HTTP 非 200 与客户端异常按类型分开。
5. 每档核对服务端：`search_log` 新增行数 == 发出请求数，`sum(search_count)` 对得上。
6. 每档结果落 JSON 到 `/stress`。
7. 中止条件：错误率 > 1%，或出现 > 10 秒的挂起；先定位再继续。
8. 每阶段清 `stress1` 的数据，绝不触碰 `123456`。
9. **读数注意**：Windows stealth mode 下连没监听的端口要等 ~2 秒才报错，"停服务后"的失败延迟含这 2 秒。

## 4. 阶段

**P0 准备**：

- `stress/stress_search.py`、`stress/make_reports_stress.py` 已就位
- 冒烟一次、确认索引规模与分片、记空闲基线

**P1 · 并发拐点**：

- `WEB_WORKERS` 固定 4，只扫并发 8 / 20 / 40 / 80，每档 200 请求，四档一次跑完、不用重启
- 要回答：峰值并发在哪一档、从哪一档开始塌
- 每档顺带报 ES queue / rejected、PG 后端与行锁、编码服务队列峰值

**P2 · B 线大数据索引**：

- 造数：`stress/make_reports_stress.py --count 30000 --recreate`；自检 `--stats`、样本 `--dry-run`
- 沿用生产 mapping 与向量口径：`report = title + summary`、同一模型与 `embed_*` 字段，直接 bulk 进索引、不落大文件
- 压测索引默认 3 分片 0 副本，生产 mapping 一个字不改
- 绕过应用直接查该索引拿天花板，再同口径走接口，差值即应用自身开销

**P3 耐久**：

- 并发 = P1 峰值并发 × 70%，长跑 10–15 分钟
- 采样内存 / 连接数 / 句柄 / ES queue / 延迟漂移
- 判据：延迟波动 ±20% 内、无错误、无单调上升趋势

**P4 故障与边界**：

- ES 停一个节点
- PG 连接池打满
- 深翻页与非法参数并发

**P5 定稿**：

- 选定默认配置写回 `.env.example` 与 `README.md`，结果表贴进 README
- 清理测试数据、提交

## 5. 命令与变量

```powershell
python -m embedding.server                    # 编码服务 127.0.0.1:8020
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH=(Get-Location).Path
$env:ENCODER_URL='http://127.0.0.1:8020'; python run.py    # API 127.0.0.1:8000
python stress/stress_search.py --requests 20 --concurrency 4 --warmup 5 --json   # 冒烟
foreach ($c in 8,20,40,80) { python stress/stress_search.py --requests 200 --concurrency $c --mode mixed --json }   # P1
python stress/stress_search.py --soak 10 --concurrency 40 --json    # P3 耐久，并发换成 P1 峰值 × 0.7
python stress/make_reports_stress.py --stats 20000                 # 分布自检
python stress/make_reports_stress.py --count 30000 --recreate      # B 线造数
# 索引为空时先灌生产数据：python scripts/ingest_reports.py
```

压测账号由脚本自建：`stress1` / `stresspass123`

| 环境变量 | 默认 | 含义 |
| --- | --- | --- |
| `WEB_WORKERS` | 4 | API 进程数 |
| `PG_POOL_MAX` | 10 | 每进程 PG 连接池上限 |
| `ES_SEARCH_WORKERS` | 自适应 | 每进程 ES 搜索连接数，不设 = `25 / WEB_WORKERS` |
| `ENCODER_URL` | 空 | 空则用进程内模型 |
| `ENCODER_MAX_BATCH` | 32 | 编码服务单批上限 |
| `ENCODER_BATCH_WAIT_MS` | 5 | 合批等待窗口 |

## 6. 结果记录

### A 线并发拐点

| 并发 | 吞吐 req/s | p50 | p95 | p99 | 错误 | 服务端核对 | run id | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8 | | | | | | | | |
| 20 | | | | | | | | |
| 40 | | | | | | | | |
| 80 | | | | | | | | |

### B 线大数据索引

| 报告数 | 层级 | 并发 | 吞吐 | p50 | p95 | ES queue | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5514 | 应用接口 | | | | | | A 线基线 |
| 3 w | ES 裸查询 | | | | | | |
| 3 w | 应用接口 | | | | | | |

### P3 耐久

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