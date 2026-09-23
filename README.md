# knowledge-search

OIRF 知识图谱的检索服务：数据导入 Elasticsearch，提供中文词法 + 向量混合检索。

另含报告数据的词法 + 向量融合检索，可按发布时间做时间衰减。

检索接口需要登录：账号与检索记录存在 PostgreSQL，登录令牌是 JWT。

## 依赖

- Python 3.12
- Docker   MongoDB + Elasticsearch 包括 analysis-ik 插件
- PostgreSQL 17  账号与检索记录；目前不在 docker compose 内

## 启动

```bash
cp .env.example .env   # ES 凭据、PG_DSN、JWT 密钥

docker compose up -d

# try: 三节点es集群 + kibana
# 首次启动需在 docker/es0*.yml 取消 cluster.initial_master_nodes 的注释
docker compose -f docker-compose.cluster.yml up -d

pip install -r requirements.txt

# 下载向量模型
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-base-zh-v1.5', cache_dir='.hf-cache/hub')"

python scripts/init_es_auth.py # 在 ES 上建 knowledge_app 角色与用户
python scripts/ingest.py       # example/*.json  -> MongoDB
python scripts/full_sync.py    # MongoDB -> Elasticsearch 一次性同步数据 + vector
python scripts/ingest_reports.py # example/reports.json -> ES 报告索引
python scripts/init_pg.py      # PostgreSQL 建表 users / search_history / search_log
python run.py                  # http://127.0.0.1:8000，检索页 /ui
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
| GET | `/api/v1/health/ready` | 公开 | 依赖就绪检查，ES / MongoDB / PostgreSQL 任一不可用返回 503 |

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
    encoder.py              bge 编码器单例与启动预热
    fields.py               权重、白名单、常量
    response.py             ES hit -> 卡片
    objects.py              /objects
    associations.py         关联子图
  mcp/server.py             MCP 工具
embedding/                  向量化
  fields.json               向量文本规范
  spec.py                   拼文本、算 hash
  encoder.py                bge 编码器
mapping/                    四个索引 mapping
schema/auth.sql             PostgreSQL 建表：用户与检索记录
docker-compose.yml          MongoDB + Elasticsearch
docker-compose.cluster.yml  三节点 ES 集群
docker/es0*.yml             各节点 ES 配置
docker/instances.yml        节点证书清单
docker/Dockerfile           ES + analysis-ik
example/                    示例数据
structure/                  OIRF v3.0 schema
docs/search-api-usage.md    接口用法
.env.example                ES 凭据、PG_DSN、JWT 密钥
scripts/                    一次性脚本
  ingest.py                 example -> MongoDB
  full_sync.py              MongoDB -> ES - 含向量
  ingest_reports.py         example/reports.json -> ES - 报告索引
  init_es_auth.py           在 ES 上建角色与用户
  init_pg.py                schema/auth.sql -> PostgreSQL 建表
static/                     静态页面：登录 / 检索 / 记录，无构建
run.py                      启动服务
```

## 许可

MIT，见 [LICENSE](LICENSE)。
