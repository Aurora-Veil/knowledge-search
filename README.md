# knowledge-search

OIRF 知识图谱的检索服务：数据导入 Elasticsearch，提供中文词法 + 向量混合检索。

另含报告数据的词法 + 向量融合检索，可按发布时间做时间衰减。

检索接口需要登录：账号与检索记录存在 PostgreSQL，登录令牌是 JWT。

具体见 [更新日志](CHANGELOG.md)

## 依赖

- Docker   内含 Elasticsearch - analysis-ik、Kibana、MongoDB、PostgreSQL、独立编码服务、API
- Python 3.12
- 编码服务使用 GPU 依赖 torch，需要可用的 NVIDIA 驱动和容器运行时

## 启动

```bash
git clone git@github.com:Aurora-Veil/knowledge-search.git
cd knowledge-search
git checkout auth
cp .env.example .env
```

`.env` 必填 `ES_ELASTIC_PASSWORD`、`ES_PASSWORD`、`KIBANA_PASSWORD`、`POSTGRES_PASSWORD`、`SECRET_KEY`、`PG_DSN`。

```bash
pip install huggingface_hub
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-base-zh-v1.5', cache_dir='.hf-cache/hub')"

mkdir -p data/es01 data/es02 data/es03 data/mongo data/kibana
sudo chown -R 1000:1000 data/es01 data/es02 data/es03 data/kibana
sudo chown -R 999:999  data/mongo
```

空数据目录上首次起集群，需在 `.env` 加如下一行，集群就绪后删掉：

```ini
ES_INITIAL_MASTER_NODES=es01,es02,es03
```

```bash
docker compose up -d
curl 127.0.0.1:8000/api/v1/health/ready   # 200 即就绪
```

无 NVIDIA 容器运行时：`docker/app.Dockerfile` 的 cu126 换成 cpu，并删掉 `docker-compose.app.yml` 里 encoder 的 `gpus: all`。

## 数据灌入脚本

依赖：

```bash
pip install -r requirements.txt
```

按顺序灌入数据：

```bash
python scripts/ingest.py          # example/*.json -> MongoDB
python scripts/full_sync.py       # MongoDB -> ES，含向量
python scripts/ingest_reports.py  # example/reports.json  -> ES 报告索引
```

索引与 ES 角色由 `es-init` 容器在 `up` 时建好，也可用脚本手动管理：

```bash
python scripts/init_es_structure.py                    # 缺什么建什么
python scripts/init_es_structure.py --list             # 看结构清单
python scripts/init_es_structure.py --recreate 索引名   # 先删后建，数据会丢
```

## 接口

| 方法 | 路径 | 鉴权 | 用途 |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/register` | 公开 | 注册，返回 201 |
| POST | `/api/v1/auth/token` | 公开 | 登录，表单换 Bearer 令牌 |
| GET | `/api/v1/auth/me` | 登录 | 当前账号 |
| POST | `/api/v1/search` | 登录 | 搜索，词法加向量再加筛选 |
| POST | `/api/v1/reports/search` | 登录 | 报告检索，词法加向量再加筛选与时间衰减 |
| GET | `/api/v1/reports/{report_id}` | 登录 | 取报告详情，含摘要 |
| GET | `/api/v1/objects/{type}/{oirf_id}` | 登录 | 取完整对象 |
| GET | `/api/v1/associations/{type}/{oirf_id}` | 登录 | 取关联子图 |
| GET | `/api/v1/projects` | 登录 | 列出项目 |
| GET | `/api/v1/history` | 登录 | 当前用户的检索记录 |
| GET | `/api/v1/health` | 公开 | 健康检查 |
| GET | `/api/v1/health/ready` | 公开 | 依赖就绪检查，ES / MongoDB / PostgreSQL 任一不可用返回 503；`encoder` 字段只报状态 |

参数、筛选取值与响应字段见 [docs/search-api-usage.md](docs/search-api-usage.md)。

服务同时以 MCP 暴露在 `http://127.0.0.1:8000/mcp`，工具定义见 `app/mcp/server.py`。
**MCP 尚未加鉴权**，暂无登录要求。

页面入口 `http://127.0.0.1:8000/ui`，含登录、OIRF 检索、报告检索、检索记录；没有构建步骤，
源码在 `static/`。登录令牌存在 localStorage，取舍见 `static/auth.js` 开头。

## 检索记录

两张表都在 PostgreSQL，建表语句见 `schema/auth.sql`：

- `search_history` —— 一行 = **用户指定q的检索**。
- `search_log` —— 一行 = **一次检索请求**。目前只写不读，没有对应接口，只能直接查表。

## 数据链路

```
example/*.json ──scripts/ingest.py──> MongoDB ──scripts/full_sync.py──> Elasticsearch
                                                └ bge-base-zh-v1.5 embedding

example/reports.json ──scripts/ingest_reports.py──> Elasticsearch
                                                     └ bge-base-zh-v1.5 embedding
```

## 压测

任务书 `stress/plan.md`，脚本 `stress/stress_search.py`、`stress/make_reports_stress.py`。
结果与结论见 [stress/report.md](stress/report.md)，原始 JSON 与日志见 `stress/stress-results-20260929.zip`。

## 目录

```
app/                        FastAPI 服务
  main.py                   应用装配、健康检查
  config.py                 连接串、索引名、检索开关
  db.py                     ES / Mongo / PostgreSQL 客户端
  serializers.py            BSON -> JSON
  routers/                  八个路由
  auth/                     注册、登录、JWT、鉴权依赖
  history/                  检索记录读写
  searchlog/                请求日志，只写不读
  search/                   检索实现
    query.py                构造 ES 查询体
    query_reports.py        构造报告查询体
    time_decay.py           时间衰减，两分支共用 rescore
    rank.py                 RRF 按名次融合
    service.py              编码、并发请求、组装响应
    service_reports.py      报告检索
    encoder.py              编码器入口：远端客户端 + 熔断 + 降级
    fields.py               权重、白名单、常量
    response.py             ES hit -> 卡片
    objects.py              /objects
    associations.py         关联子图
  mcp/server.py             MCP 工具
embedding/                  向量化
  fields.json               向量文本规范
  spec.py                   拼文本、算 hash
  encoder.py                bge 编码器
  server.py                 独立编码服务：单进程、query 合批
mapping/                    四个索引 mapping
schema/auth.sql             PostgreSQL 建表：用户与检索记录
docker-compose.cluster.yml  三节点 ES 集群
docker-compose.app.yml      MongoDB + PostgreSQL + 编码服务 + API
docker/app.Dockerfile       应用镜像，两个 target：API / 编码服务
docker/es0*.yml             各节点 ES 配置
docker/instances.yml        节点证书清单
docker/Dockerfile           ES + analysis-ik
requirements.txt            依赖清单；带 encoder-only 标记的只在编码服务装
.dockerignore               构建上下文排除项
example/                    示例数据
structure/                  OIRF v3.0 schema
docs/search-api-usage.md    接口用法
.env.example                ES 凭据、PG_DSN、JWT 密钥、编码服务与并发参数
scripts/
  init_es_auth.py           在 ES 上建角色与用户，已由 es-init 容器自动跑
  init_es_structure.py      按 mapping/ 建索引，已由 es-init 容器自动跑
  ingest.py                 example -> MongoDB
  full_sync.py              MongoDB -> ES - 含向量
  ingest_reports.py         example/reports.json -> ES - 报告索引
  smoke_report_search.py    端到端冒烟：登录 + 报告检索，退 0 即通过
static/                     静态页面：登录 / 检索 / 记录，无构建
stress/                     压测：任务书、脚本与结果
```

## 许可

MIT，见 [LICENSE](LICENSE)。
