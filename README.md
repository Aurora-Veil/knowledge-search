# knowledge-search

OIRF 知识图谱的检索服务：数据导入 Elasticsearch，提供中文词法 + 向量混合检索。

另含报告数据的词法 + 向量融合检索，可按发布时间做时间衰减。

## 依赖

- Python 3.12
- Docker   MongoDB + Elasticsearch 包括 analysis-ik 插件

## 启动

```bash
cp .env.example .env   # 用户与密码设置

docker compose up -d

pip install -r requirements.txt

# 下载向量模型
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-base-zh-v1.5', cache_dir='.hf-cache/hub')"

python scripts/init_es_auth.py # 在 ES 上建 knowledge_app 角色与用户
python scripts/ingest.py       # example/*.json  -> MongoDB
python scripts/full_sync.py    # MongoDB -> Elasticsearch 一次性同步数据 + vector
python scripts/ingest_reports.py # example/reports.json -> ES 报告索引
python run.py                  # http://127.0.0.1:8000，检索页 /ui
```

## 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/search` | 搜索，词法加向量再加筛选 |
| GET | `/api/v1/objects/{type}/{oirf_id}` | 取完整对象 |
| GET | `/api/v1/associations/{type}/{oirf_id}` | 取关联子图 |
| GET | `/api/v1/projects` | 列出项目 |
| POST | `/api/v1/reports/search` | 报告检索，词法加向量再加筛选与时间衰减 |
| GET | `/api/v1/reports/{report_id}` | 取报告详情，含摘要 |
| GET | `/api/v1/health` | 健康检查 |

参数、筛选取值与响应字段见 [docs/search-api-usage.md](docs/search-api-usage.md)。

服务同时以 MCP 暴露在 `http://127.0.0.1:8000/mcp`，工具定义见 `app/mcp/server.py`。

检索页面入口 `http://127.0.0.1:8000/ui`，内含报告检索与 OIRF 检索两个入口页；页面源码在 `static/`。

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
  db.py                     ES / Mongo 客户端
  serializers.py            BSON -> JSON
  routers/                  五个路由
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
docker-compose.yml          MongoDB + Elasticsearch
docker/Dockerfile           ES + analysis-ik
example/                    示例数据
structure/                  OIRF v3.0 schema
docs/search-api-usage.md    接口用法
.env.example                ES user & key
scripts/                    一次性脚本
  ingest.py                 example -> MongoDB
  full_sync.py              MongoDB -> ES - 含向量
  ingest_reports.py         example/reports.json -> ES - 报告索引
  init_es_auth.py           在 ES 上建角色与用户
static/                     检索页面
run.py                      启动服务
```

## 许可

MIT，见 [LICENSE](LICENSE)。
