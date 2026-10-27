# 搜索 API

服务地址 `http://127.0.0.1:8000`，交互文档 `/docs`。下文 `$API` 指 `http://127.0.0.1:8000/api/v1`。

除注册、登录和健康检查外，都要带：

```http
Authorization: Bearer <token>
```

```bash
# 注册
curl -s -X POST "$API/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"demo-password"}'

# 登录，取出令牌
TOKEN=$(curl -s -X POST "$API/auth/token" \
  -d 'username=demo&password=demo-password' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
```

## 端点

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/health` | 健康检查 |
| `GET /api/v1/health/ready` | 依赖就绪检查 |
| `POST /api/v1/auth/register` | 注册 |
| `POST /api/v1/auth/token` | 登录 |
| `GET /api/v1/auth/me` | 当前账号 |
| `POST /api/v1/search` | 对象检索 |
| `GET /api/v1/objects/{object_type}/{oirf_id}` | 完整对象 |
| `GET /api/v1/associations/{object_type}/{oirf_id}` | 关联子图 |
| `GET /api/v1/projects` | 项目列表 |
| `GET /api/v1/history` | 检索记录 |
| `POST /api/v1/reports/search` | 报告检索 |
| `GET /api/v1/reports/{report_id}` | 报告详情 |
| `GET /api/v1/stats/report-library` | 报告库统计 |
| `GET /api/v1/stats/search-activity` | 检索统计 |

`object_type` 取 `source`、`evidence`、`viewpoint`。对象与关联属于图谱，报告是独立数据集。

## 对象检索

`POST /api/v1/search`

| 字段 | 说明 |
| --- | --- |
| `q` | 检索词，可省略；省略时只做筛选 |
| `type` | `source`、`evidence`、`viewpoint`、`all`，默认 `all` |
| `project_id` | 单个 ID 或 ID 数组；省略为全部项目 |
| `mode` | `or`、`and`、`phrase`，只影响词法分支；`phrase` 要求相邻 |
| `page`、`size` | 默认 `1`、`20`，`size` 最大 `100`，`page * size` 不超过 `200` |
| `highlight` | 是否返回 `<em>` 高亮，默认 `true` |

筛选字段都是精确匹配：

| 字段 | 适用对象 |
| --- | --- |
| `status`、`presentation_type`、`responsible_role` | 三类 |
| `period`、`region`、`industry`、`source_type` | evidence |
| `confidence_level`、`publisher` | source、evidence |
| `claim_type`、`applicable_scenario`、`cross_validation_mode`、`evidence_ids` | viewpoint |
| `source_ids` | evidence、viewpoint |

`type=all` 时，筛选对某类不适用，该类直接排除。`source_ids` 和 `evidence_ids` 用于引用溯源。筛选取值以实际入库数据为准。

`q` 同时走词法和向量。向量比对整篇拼接文本，词法只匹配固定的名称、标题、指标等字段，所以 `total` 只代表词法命中，可能小于 `hits` 条数。

```bash
curl -s -X POST "$API/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"q":"空间计算","type":"evidence","industry":"空间计算设备","size":3}'
```

```jsonc
{
  "total": 23,
  "page": 1,
  "size": 3,
  "degraded": false,
  "hits": [
    {
      "id": "6a9fbd1b270db0c081be679d",
      "object_type": "evidence",
      "project_id": 1,
      "oirf_id": "evidence:E028",
      "score": 0.0325,
      "raw_score": 25.6,
      "knn_score": 0.748,
      "match_source": "both",
      "identity": { "name": "…", "status": "PENDING" },
      "presentation": { "subject": "苹果", "period": "2024" },
      "highlight": { "identity.name": ["<em>空间</em>计算"] }
    }
  ]
}
```

带 `q` 时 `score` 是 RRF 名次分，`raw_score` 是 BM25，`knn_score` 是向量分，不要跨查询比较；纯筛选时 `score` 为 0。编码不可用且本次需要向量时，`degraded=true`，`match_source` 只剩 `bm25`。

列表只返回卡片。长文本用对象详情取。

## 完整对象

`GET /api/v1/objects/{object_type}/{oirf_id}?project_id=1`

`project_id` 必填。`oirf_id` 只在项目内唯一。

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$API/objects/viewpoint/viewpoint:V001?project_id=1"
```

响应包含 `identity`、`presentation`、`reasoning`、`experience`、`responsibility`、`lifecycle` 等完整字段。

## 关联子图

`GET /api/v1/associations/{object_type}/{oirf_id}?project_id=1`

`project_id` 必填。`hops` 取 `1` 或 `2`；`direction` 取 `out`、`in`、`both`；`types` 是逗号分隔的对象类型；`include` 取 `card` 或 `ref`；`limit` 是每个方向与类型组合的上限，默认 `50`，最大 `200`。

```jsonc
{
  "root": { "oirf_id": "viewpoint:V001", "object_type": "viewpoint" },
  "project_id": 1,
  "hops": 1,
  "direction": "out",
  "include": "card",
  "nodes": [{ "oirf_id": "evidence:E005", "object_type": "evidence" }],
  "edges": [{
    "from": "viewpoint:V001",
    "to": "evidence:E005",
    "rel": "step_evidence",
    "step": 0,
    "hop": 1,
    "label": "…"
  }],
  "truncated": [],
  "missing": []
}
```

`viewpoint` 没有入边，`source` 没有出边。`truncated` 列出被截断的桶，`missing` 列出被引用但取不到的节点。

## 项目

`GET /api/v1/projects`

```jsonc
{
  "projects": [
    { "project_id": 1, "source": 24, "evidence": 349, "viewpoint": 24 }
  ],
  "total_objects": 397
}
```

## 报告检索

`POST /api/v1/reports/search`

| 字段 | 说明 |
| --- | --- |
| `q` | 必填，词法和向量两路召回 |
| `mode` | `or`、`and`、`phrase` |
| `time_weight` | 时间衰减权重，`0` 到 `1`，默认 `0` |
| `report_id` | 报告 ID 数组，精确匹配 |
| `layout` | `横版` 或 `竖版` |
| `industry` | 行业数组，精确匹配 |
| `publish_date_from`、`publish_date_to` | 发布日闭区间，`YYYY-MM-DD` |
| `page`、`size` | 默认 `1`、`20`，`page * size` 不超过 `200` |
| `highlight` | 默认 `true` |

`q` 的词法权重是 `title` 3、`industry.text` 2、`summary` 1，向量文本是 `title + summary`。`time_weight` 只改排序，不改变命中文档。

```bash
curl -s -X POST "$API/reports/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"q":"氢能产业园","layout":"横版","size":3}'
```

```jsonc
{
  "total": 9,
  "page": 1,
  "size": 3,
  "degraded": false,
  "hits": [
    {
      "report_id": "62e33fbc2f669532f23e1cd8",
      "title": "2022年中国氢能产业园研究报告",
      "industry": [],
      "layout": "横版",
      "publish_date": "2022-07-29",
      "url": "https://…",
      "score": 0.0325,
      "raw_score": 12.4,
      "knn_score": 0.8123,
      "match_source": "both",
      "highlight": { "title": ["<em>氢能</em>产业园"] }
    }
  ]
}
```

`total` 同样只统计词法命中，`degraded` 含义与对象检索相同。列表不含 `summary`。

详情：

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$API/reports/62e33fbc2f669532f23e1cd8"
```

详情比列表多 `summary`，少 `score`、`raw_score`、`knn_score`、`match_source`、`highlight`。

## 检索记录

`GET /api/v1/history?kind=oirf&limit=5`

`kind` 取 `oirf` 或 `report`，省略为全部。`limit` 默认 `20`，最大 `100`。

```jsonc
[
  {
    "id": 1,
    "kind": "oirf",
    "query": "空间计算",
    "filters": { "type": "evidence", "industry": "空间计算设备" },
    "last_page": 3,
    "size": 20,
    "result_total": 23,
    "search_count": 3,
    "first_seen_at": "2026-10-01T10:00:00+08:00",
    "last_seen_at": "2026-10-01T10:05:00+08:00"
  }
]
```

`kind`、`query`、`filters` 相同就是同一条记录。翻页不新增行，只更新 `last_page` 和 `result_total`；`search_count` 只在 `page=1` 时加一。

## 错误

| 状态 | 场景 |
| --- | --- |
| `400` | 分页超过 200、对象详情 `object_type` 非法、报告 `q` 只有空白 |
| `401` | 缺少、无效或过期的令牌 |
| `403` | 账号已停用 |
| `404` | 对象、关联根节点或报告不存在 |
| `409` | 注册时用户名已被占用 |
| `422` | 参数类型或取值不合法，或缺少 `project_id` |
| `503` | 账号、历史、统计或健康检查依赖不可用 |

统计接口见 [stats-api-usage.md](stats-api-usage.md)。
