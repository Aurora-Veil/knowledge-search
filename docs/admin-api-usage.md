# 后台 API

`/api/v1/admin/*` 只有管理员能调，普通账号返回 `403`。都要带 `Authorization: Bearer <token>`。

`$API` 指 `http://127.0.0.1:8000/api/v1`。

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/admin/stats/report-library` | 报告库统计 |
| `GET /api/v1/admin/stats/search-activity` | 检索趋势与 Top 词 |
| `GET /api/v1/admin/users` | 用户列表 |
| `GET /api/v1/admin/users/{id}` | 用户详情 |
| `PATCH /api/v1/admin/users/{id}` | 改角色、停用、启用 |
| `GET /api/v1/admin/actions` | 操作记录 |
| `GET /api/v1/admin/search-logs` | 检索请求明细 |
| `GET /api/v1/admin/search-logs/summary` | 检索请求汇总 |

首个管理员建表后没有，只能手工升：

```bash
docker compose exec -T pg psql -U postgres -d knowledge_db \
  -c "UPDATE users SET role = 'admin' WHERE username = '<账号>';"
```

## 报告库

`GET /api/v1/admin/stats/report-library`，无参数，缓存 10 分钟。

```bash
curl -H "Authorization: Bearer $TOKEN" "$API/admin/stats/report-library"
```

```jsonc
{
  "total": 5514,
  "years": [
    {
      "year": 2024,
      "count": 830,
      "industry_total": 420,
      "industries": [{ "name": "锂电池", "count": 36 }]
    }
  ],
  "industries": [
    { "name": "锂电池", "count": 214, "years": [{ "year": 2024, "count": 36 }] }
  ],
  "industry_years": {
    "锂电池": { "count": 214, "years": [{ "year": 2024, "count": 36 }] }
  },
  "industry_count": 1789,
  "layouts": [{ "name": "横版", "count": 4209 }],
  "publish_range": { "from": "2018-03-05", "to": "2026-08-21" },
  "generated_at": "2026-10-27T02:31:07+00:00"
}
```

| 字段 | 说明 |
| --- | --- |
| `total` | 报告总数 |
| `years[]` | 发布年、数量、当年行业数、当年 Top 行业 |
| `industries[]` | 全局 Top 10 行业，带逐年数量 |
| `industry_years` | 行业到逐年数量的映射 |
| `industry_count` | 行业去重总数 |
| `layouts[]` | 版式及数量，最多 10 条 |
| `publish_range` | 最早、最晚发布日，空库为 `null` |
| `generated_at` | 生成时间，UTC |

`years` 覆盖最早到最晚发布年，缺年补 0。`industries` 和 `layouts` 只列 Top 10，`industry_total` 可能比 `industries` 的条数大。ES 不可用返回 `503`。

## 检索趋势

`GET /api/v1/admin/stats/search-activity`，读 `search_daily`，缓存 10 分钟到 24 小时。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `start` | `end - days + 1` | 起始日，含 |
| `end` | 今天 | 结束日，含 |
| `days` | `14` | 回看天数，`1` 到 `366` |
| `queries` | 无 | 可重复，最多 20 个，精确匹配 |
| `kind` | 全部 | `oirf` 或 `report` |
| `granularity` | `day` | `day`、`week`、`month` |
| `limit` | `5` | `top_queries` 条数，`1` 到 `20` |

```bash
curl -G -H "Authorization: Bearer $TOKEN" "$API/admin/stats/search-activity" \
  --data-urlencode "days=1" --data-urlencode "queries=储能" --data-urlencode "limit=3"
```

```jsonc
{
  "range": { "start": "2026-10-26", "end": "2026-10-26", "granularity": "day" },
  "data_until": "2026-10-26",
  "daily": [
    { "date": "2026-10-26", "searches": 41, "zero_result": 4, "errors": 0,
      "latency_sum": 16800, "ok_count": 41 }
  ],
  "top_queries": [{ "query": "储能装机量", "count": 18 }],
  "selected": [{ "query": "储能", "count": 41 }],
  "totals": {
    "searches": 41, "zero_result": 4, "errors": 0, "zero_result_rate": 0.0976,
    "latency_sum": 16800, "ok_count": 41, "avg_latency_ms": 410
  }
}
```

只统计 `page = 1`，日期按 `Asia/Shanghai` 切。`queries` 只影响 `daily`、`selected`、`totals`，`top_queries` 始终是全站口径。

跨度超过 366 天、`queries` 超过 20 个返回 `422`。

## 用户列表

`GET /api/v1/admin/users`

| 参数 | 说明 |
| --- | --- |
| `q` | 用户名模糊匹配，`%` 和 `_` 按字面处理 |
| `role` | `user` 或 `admin`，不传为全部 |
| `active` | `true` 或 `false`，不传为全部 |
| `limit` | 默认 20，最大 100 |
| `offset` | 默认 0 |

```bash
curl -H "Authorization: Bearer $TOKEN" "$API/admin/users?q=zhang&role=user"
```

```jsonc
{
  "total": 133,
  "items": [
    { "id": 7, "username": "zhangsan", "role": "user", "is_active": true,
      "created_at": "2026-10-12T09:31:04+08:00",
      "search_count": 214, "last_seen_at": "2026-11-01T21:03:11+08:00" }
  ]
}
```

`total` 是筛选后的总数。`search_count` 是该账号累计检索次数，翻页不重复计；没检索过是 0，`last_seen_at` 为 `null`。按 `id` 升序。

## 用户详情与修改

`GET /api/v1/admin/users/{id}` 返回同列表项，不存在返回 `404`。

`PATCH /api/v1/admin/users/{id}`

```jsonc
{ "role": "admin" }
{ "is_active": false }
```

两个字段都可选，省略的保持不变，至少给一个。

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"is_active": false}' "$API/admin/users/7"
```

| 情况 | 状态 |
| --- | --- |
| 用户不存在 | `404` |
| 停用或降级自己 | `400` |
| 撤掉最后一个启用中的管理员 | `409` |
| 一个字段都没给 | `422` |

改完最多 5 秒生效。返回改完的那一行。

## 操作记录

`GET /api/v1/admin/actions`，新的在前。

| 参数 | 说明 |
| --- | --- |
| `action` | `user_update` 或 `password_reset` |
| `actor_id` | 只看某个操作人 |
| `target_id` | 只看某个被改账号 |
| `limit` | 默认 20，最大 100 |
| `offset` | 默认 0 |

```jsonc
{
  "total": 3,
  "items": [
    { "id": 3, "actor_id": 1, "actor_username": "admin", "action": "user_update",
      "target_id": 7, "target_username": "zhangsan",
      "detail": { "changes": { "role": ["user", "admin"] } },
      "created_at": "2026-11-02T15:12:03+08:00" }
  ]
}
```

`detail.changes` 是字段到旧值、新值的映射。账号被删时用户名是 `null`。

## 检索请求明细

`GET /api/v1/admin/search-logs`，按时间倒序。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `start` | `end - days + 1` | 起始日，含 |
| `end` | 今天 | 结束日，含 |
| `days` | `7` | 回看天数，`1` 到 `30` |
| `kind` | 全部 | `oirf` 或 `report` |
| `outcome` | 全部 | `ok` 或 `error` |
| `user_id` | 全部 | 只看某个账号 |
| `cursor` | 无 | 上一页返回的 `next` |
| `limit` | `50` | 最大 200 |

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$API/admin/search-logs?days=1&outcome=error&limit=20"
```

```jsonc
{
  "items": [
    { "id": 3160521, "request_id": "9e95b7c38788", "user_id": 2,
      "username": "stress1", "kind": "report", "query": "工业机器人应用场景",
      "filters": { "mode": "phrase" }, "page": 1, "size": 20,
      "outcome": "ok", "status_code": 200, "error_type": null,
      "result_total": 0, "latency_ms": 850,
      "created_at": "2026-11-02T03:18:18.921396Z" }
  ],
  "next": "2026-11-02T03:18:18.921396Z|3160521"
}
```

`next` 为 `null` 表示没有下一页，翻页时原样带回 `cursor`。这里的明细包含翻页请求，汇总只算首页。

窗口超过 30 天、游标格式不对返回 `422`。

## 检索请求汇总

`GET /api/v1/admin/search-logs/summary`，参数同明细，去掉 `outcome`、`cursor`、`limit`。只读按天的小表，不读 `search_log`。

```jsonc
{
  "range": { "start": "2026-10-05", "end": "2026-11-02", "requested_end": "2026-11-03" },
  "data_until": "2026-11-02",
  "user_id": null,
  "searches": 2910781,
  "zero_result": 75081,
  "errors": 3,
  "error_rate": 0.000001,
  "zero_result_rate": 0.0258,
  "avg_latency_ms": 400,
  "latency_ms": { "p50": 200, "p95": 1000, "p99": 1000 },
  "by_kind": [
    { "kind": "oirf", "searches": 30, "errors": 0, "zero_result": 18,
      "error_rate": 0, "zero_result_rate": 0.6, "avg_latency_ms": 70 }
  ],
  "top_errors": [{ "error_type": "ValueError", "count": 3 }]
}
```

- `searches` 只算 `page = 1`，`errors` 和 `zero_result` 是它的子集。
- `errors` 只统计首页的错误，明细里的错误包含翻页请求。
- `latency_ms` 从 50 毫秒一档的直方图估算，超过 1000 毫秒一律报 `1000`。
- 今天的数据还没汇总，`end` 截到 `data_until`，`requested_end` 是请求的结束日。
- 带 `user_id` 时读 `search_user_daily`，`latency_ms` 和 `top_errors` 不适用，返回 `null` 和空列表。

## 数据更新

四张按天的小表由下面的命令写入，每天跑一次：

```bash
python -m app.searchlog.rollup
```

首次上线或补历史：

```bash
python -m app.searchlog.rollup --backfill
```

只重算某一天用 `--date 2026-11-02`，最近 N 天用 `--days 7`。每天一个事务，可重复执行。
