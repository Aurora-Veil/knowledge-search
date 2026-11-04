# 概览统计 API

检索端只有一个概览接口，数据来自 Elasticsearch 聚合。全站统计、用户管理和检索日志在 [admin-api-usage.md](admin-api-usage.md)。

要带 `Authorization: Bearer <token>`。

`$API` 指 `http://127.0.0.1:8000/api/v1`。

## 概览数字

`GET /api/v1/stats/summary`，无参数。登录即可调，检索首页那一行字用它。

```bash
curl -H "Authorization: Bearer $TOKEN" "$API/stats/summary"
```

```jsonc
{
  "total": 5514,
  "industry_count": 1789,
  "publish_range": { "from": "2018-03-05", "to": "2026-08-21" },
  "generated_at": "2026-11-02T07:12:40+00:00"
}
```

| 字段 | 说明 |
| --- | --- |
| `total` | 报告总数 |
| `industry_count` | 行业去重总数 |
| `publish_range` | 最早、最晚发布日，空库为 `null` |
| `generated_at` | 生成时间，UTC |

只跑总量、行业去重数和发布区间三个聚合，缓存 10 分钟。ES 不可用返回 `503`。
