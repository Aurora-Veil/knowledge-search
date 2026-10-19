# knowledge-search

OIRF 知识图谱的检索服务：数据导入 Elasticsearch，提供中文词法 + 向量混合检索。

另含报告数据的词法 + 向量融合检索，可按发布时间做时间衰减。

检索接口需要登录：账号与检索记录存在 PostgreSQL，登录令牌是 JWT。

具体见 [更新日志](CHANGELOG.md)

## 依赖

- Docker   内含 Elasticsearch - analysis-ik、Kibana、MongoDB、PostgreSQL、Redis、独立编码服务、API
- Python 3.12
- 编码服务使用 GPU 依赖 torch，需要可用的 NVIDIA 驱动和容器运行时

## 启动

```bash
git clone git@github.com:Aurora-Veil/knowledge-search.git
cd knowledge-search
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
| GET | `/api/v1/health/ready` | 公开 | 依赖就绪检查，ES / MongoDB / PostgreSQL 任一不可用返回 503；`encoder` 与 `cache` 字段只报状态 |

参数、筛选取值与响应字段见 [docs/search-api-usage.md](docs/search-api-usage.md)。

服务同时以 MCP 暴露在 `http://127.0.0.1:8000/mcp`，工具定义见 `app/mcp/server.py`。
**MCP 尚未加鉴权**，暂无登录要求。

页面入口 `http://127.0.0.1:8000/ui`，含登录、OIRF 检索、报告检索、检索记录；没有构建步骤，
源码在 `static/`。登录令牌存在 localStorage，取舍见 `static/auth.js` 开头。

## 检索记录

两张表都在 PostgreSQL，建表语句见 `schema/auth.sql`：

- `search_history` —— 一行 = **用户指定q的检索**。
- `search_log` —— 一行 = **一次检索请求**。目前只写不读，没有对应接口，只能直接查表。

## 检索缓存

`POST /api/v1/reports/search` 的响应体进 Redis，键是规范化参数的 sha256，过期时刻固定为下一个午夜。

q 的向量另存 PostgreSQL 的 `query_vec` 表：结果未命中时先取向量，取到就不再调编码服务。键含模型与指令哈希，编码配置一变整表失效。

两侧都只是检索加速器。

## 数据链路

```
example/*.json ──scripts/ingest.py──> MongoDB ──scripts/full_sync.py──> Elasticsearch
                                                └ bge-base-zh-v1.5 embedding

example/reports.json ──scripts/ingest_reports.py──> Elasticsearch
                                                     └ bge-base-zh-v1.5 embedding
```

## 压测

脚本在 `stress/scripts/`：`ramp_load.py` 固定词表加压，`ramp_mixed.py` 按页面真实的请求形态组合词、翻页与筛选，`watch_containers.py` 采容器指标。

报告在 [stress/reports/](stress/reports/)，仅有最新报告。

## 目录

```
app/                        FastAPI 服务：路由、鉴权、检索、缓存
  search/                   查询体、RRF、时间衰减、q 向量缓存
  cache/                    结果缓存：键规范化与 Redis 读写
  routers/ auth/ history/   路由、鉴权、检索记录
  searchlog/                请求日志，只写不读
  mcp/server.py             MCP 工具
embedding/                  文本规范、bge 编码器、独立编码服务
mapping/                    四个索引 mapping
schema/                     PostgreSQL 建表：用户、检索记录、q 向量缓存
docker/                     应用镜像与 ES 节点配置
docker-compose*.yml         三节点 ES 集群 / 应用栈
example/                    示例数据
structure/                  OIRF v3.0 schema
docs/                       接口用法、缓存方案、容量方案
scripts/                    灌数、初始化 ES、q 向量灌库
static/                     静态页面：登录 / 检索 / 记录，无构建
stress/                     压测脚本与报告，archive 为历史资产
requirements.txt            依赖清单，encoder-only 标记的只在编码服务装
.env.example                ES 凭据、PG_DSN、JWT 密钥、编码服务与并发参数、缓存开关
```

## 许可

MIT，见 [LICENSE](LICENSE)。
