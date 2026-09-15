# knowledge-search

OIRF 知识图谱的检索服务：数据导入 Elasticsearch，提供中文词法 + 向量混合检索。

## 依赖

- Python 3.12
- MongoDB（`localhost:27017`，库 `knowledge_db`）
- Elasticsearch 9.x（`localhost:9200`，需 **analysis-ik** 分词插件）

## 启动

```bash
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

| 路径 | 内容 |
| --- | --- |
| `app/` | FastAPI 服务；`app/search/` 为检索实现 |
| `embedding/` | `fields.json` 定义向量文本、`spec.py` 拼接、`encoder.py` 编码 |
| `mapping/` | 三个索引的 mapping |
| `structure/` | OIRF v3.0 schema |
| `docs/` | 文档 |
