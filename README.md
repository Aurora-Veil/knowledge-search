# knowledge-search

OIRF 知识图谱与报告检索服务。中文词法与向量混合检索，检索接口需要登录。

更新见 [CHANGELOG.md](CHANGELOG.md)。

## 启动

需要 Docker、Docker Compose、Python 3.12。GPU 编码还需要 NVIDIA 驱动与容器运行时。

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
sudo chown -R 999:999 data/mongo
```

空目录首次启动集群时，在 `.env` 加 `ES_INITIAL_MASTER_NODES=es01,es02,es03`，就绪后删除。

```bash
docker compose up -d
curl 127.0.0.1:8000/api/v1/health/ready
```

返回 200 即就绪。

没有 NVIDIA 容器运行时，将 `docker/app.Dockerfile` 的 `cu126` 改为 `cpu`，并删除 `docker-compose.app.yml` 中 encoder 的 `gpus: all`。

## 导入数据

```bash
pip install -r requirements.txt
python scripts/ingest.py
python scripts/full_sync.py
python scripts/ingest_reports.py
```

依次导入示例数据、同步到 Elasticsearch、灌入报告索引。索引与 ES 角色由 `es-init` 容器创建。

手动重建用 `scripts/init_es_structure.py`，`--recreate` 会清空数据。

## 接口

除注册、登录和健康检查外，都需要 `Authorization: Bearer <token>`。

| 接口 | 用途 |
| --- | --- |
| `POST /api/v1/auth/register` | 注册 |
| `POST /api/v1/auth/token` | 登录 |
| `GET /api/v1/auth/me` | 当前账号 |
| `POST /api/v1/search` | 对象检索 |
| `POST /api/v1/reports/search` | 报告检索 |
| `GET /api/v1/reports/{report_id}` | 报告详情 |
| `GET /api/v1/objects/{object_type}/{oirf_id}` | 对象详情 |
| `GET /api/v1/associations/{object_type}/{oirf_id}` | 关联子图 |
| `GET /api/v1/projects` | 项目列表 |
| `GET /api/v1/history` | 检索记录 |
| `GET /api/v1/stats/report-library` | 报告库概览 |
| `GET /api/v1/stats/search-activity` | 检索趋势 |
| `GET /api/v1/health` | 健康检查 |
| `GET /api/v1/health/ready` | 依赖就绪检查 |

参数与响应见 [docs/search-api-usage.md](docs/search-api-usage.md) 和 [docs/stats-api-usage.md](docs/stats-api-usage.md)。

MCP 服务在 `http://127.0.0.1:8000/mcp`，工具定义见 `app/mcp/server.py`。**MCP 目前没有鉴权。**

## 前端

页面在 `http://127.0.0.1:8000/ui/`，源码在 `dashboard/`，构建产物在 `static/`。

```bash
cd dashboard
pnpm dev
```

开发地址是 `http://127.0.0.1:5173/ui/`，Vite 会代理接口与文档请求。

构建用 `pnpm build`，将 `dist/` 复制到 `static/`，再重建 `api` 镜像。详见 [dashboard/README.md](dashboard/README.md)。

## 数据与缓存

- `search_history` 用户发起的检索
- `search_log` 每次检索请求，只写不读
- `search_daily` 按天聚合，概览只读这张表

`search_daily` 由 `python -m app.searchlog.rollup` 每日更新。

报告检索结果缓存在 Redis，次日零点过期。查询向量存在 PostgreSQL 的 `query_vec`，编码配置变化后整表失效。

## 压测

脚本在 `stress/scripts/`，报告在 `stress/reports/`。

## 目录

```text
app/              FastAPI 服务
dashboard/        React 前端
embedding/        编码器与编码服务
mapping/          Elasticsearch mapping
schema/           PostgreSQL 建表
docker/           镜像与集群配置
scripts/          数据导入与初始化
docs/             接口与方案文档
static/           前端构建产物
stress/           压测
```

## 许可

MIT，见 [LICENSE](LICENSE)。
