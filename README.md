# knowledge-search

OIRF 知识图谱的检索服务：数据导入 Elasticsearch，提供中文词法 + 向量混合检索。

## 依赖

- Python 3.12
- Docker   MongoDB + Elasticsearch 包括 analysis-ik 插件

## 启动

```bash
docker compose up -d   # 首次会构建带 analysis-ik 的 ES 镜像

pip install -r requirements.txt

# 首次：下载向量模型
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-base-zh-v1.5', cache_dir='.hf-cache/hub')"

python ingest.py       # example/*.json  -> MongoDB
python full_sync.py    # MongoDB -> Elasticsearch 一次性同步数据 + vector
python run.py          # http://127.0.0.1:8000
```

## 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/search` | 搜索，词法加向量再加筛选 |
| GET | `/api/v1/objects/{type}/{oirf_id}` | 取完整对象 |
| GET | `/api/v1/associations/{type}/{oirf_id}` | 取关联子图 |
| GET | `/api/v1/projects` | 列出项目 |
| GET | `/api/v1/health` | 健康检查 |

参数、筛选取值与响应字段见 [docs/search-api-usage.md](docs/search-api-usage.md)。

## 数据链路

```
example/*.json ──ingest.py──> MongoDB ──full_sync.py──> Elasticsearch
                                            └ bge-base-zh-v1.5 embedding
```

## 目录

```
app/                        FastAPI 服务
  main.py                   应用装配、健康检查
  config.py                 连接串、索引名、检索开关
  db.py                     ES / Mongo 客户端
  serializers.py            BSON -> JSON
  routers/                  四个路由
  search/                   检索实现
    query.py                构造 ES 查询体
    rank.py                 RRF 按名次融合
    service.py              编码、并发请求、组装响应
    fields.py               权重、白名单、常量
    response.py             ES hit -> 卡片
    objects.py              /objects（Mongo）
    associations.py         关联子图
  mcp/server.py             MCP 工具
embedding/                  向量化
  fields.json               向量文本规范
  spec.py                   拼文本、算 hash
  encoder.py                bge 编码器
mapping/                    三个索引 mapping
docker-compose.yml          MongoDB + Elasticsearch
docker/Dockerfile           ES + analysis-ik
example/                    示例数据
structure/                  OIRF v3.0 schema
docs/search-api-usage.md    接口用法
ingest.py                   example -> MongoDB
full_sync.py                MongoDB -> ES - 含向量
run.py                      启动服务
```

## 许可

MIT，见 [LICENSE](LICENSE)。
