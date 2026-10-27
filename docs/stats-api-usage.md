# 概览统计 API

两个只读接口，返回聚合值，不带单条日志和用户身份。都要带 `Authorization: Bearer <token>`。

`$API` 指 `http://127.0.0.1:8000/api/v1`。

| 接口 | 数据源 | 用途 |
| --- | --- | --- |
| `GET /api/v1/stats/report-library` | Elasticsearch 聚合 | 报告总量、年份、行业、版式、发布区间 |
| `GET /api/v1/stats/search-activity` | `search_daily` | 检索量、零结果、失败、Top 词 |

`search-activity` 只读 `search_daily`，不读 `search_log`。汇总表通常只到昨天，`data_until` 是实际最后一天。

结果会缓存：报告库 10 分钟；检索行为结束日早于今天时缓存 24 小时，否则 60 秒。

## 报告库

`GET /api/v1/stats/report-library`，无参数。

```bash
curl -H "Authorization: Bearer $TOKEN" "$API/stats/report-library"
```

```jsonc
{
  "total": 5514,
  "years": [
    {
      "year": 2024,
      "count": 830,
      "industry_total": 420,
      "industries": [
        { "name": "锂电池", "count": 36 }
      ]
    }
  ],
  "industries": [
    {
      "name": "锂电池",
      "count": 214,
      "years": [
        { "year": 2024, "count": 36 }
      ]
    }
  ],
  "industry_years": {
    "锂电池": {
      "count": 214,
      "years": [
        { "year": 2024, "count": 36 }
      ]
    }
  },
  "industry_count": 1789,
  "layouts": [
    { "name": "横版", "count": 4209 },
    { "name": "竖版", "count": 1305 }
  ],
  "publish_range": { "from": "2018-03-05", "to": "2026-08-21" },
  "generated_at": "2026-10-27T02:31:07+00:00"
}
```

示例只列一年和一个行业；实际 `years` 覆盖全部发布年，`industries` 与 `layouts` 最多 10 条。

| 字段 | 说明 |
| --- | --- |
| `total` | 报告总数 |
| `years[]` | 发布年、数量、当年行业数、当年 Top 行业 |
| `industries[]` | 全局 Top 10 行业，带逐年数量 |
| `industry_years` | 行业到逐年数量的映射，覆盖全局和年度 Top 行业 |
| `industry_count` | 行业去重总数 |
| `layouts[]` | 版式及数量，最多 10 条 |
| `publish_range` | 最早、最晚发布日，空库为 `null` |
| `generated_at` | 生成时间，UTC |

`years` 只覆盖最早到最晚发布年，中间缺年补 0。`years[].industry_total` 是当年行业去重数，可能大于该年的 `industries` 条数，因为后者只列 Top 10。

ES 不可用时返回 `503`。

## 检索行为

`GET /api/v1/stats/search-activity`

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `start` | `end - days + 1` | 起始日，含 |
| `end` | 今天 | 结束日，含 |
| `days` | `14` | 回看天数，`1` 到 `366`，只在缺 `start` 时生效 |
| `queries` | 无 | 可重复，最多 20 个，精确匹配 |
| `kind` | 全部 | `oirf` 或 `report` |
| `granularity` | `day` | `day`、`week`、`month` |
| `limit` | `5` | `top_queries` 条数，`1` 到 `20` |

```bash
curl -G -H "Authorization: Bearer $TOKEN" "$API/stats/search-activity" \
  --data-urlencode "days=1" \
  --data-urlencode "queries=储能" \
  --data-urlencode "limit=3"
```

```jsonc
{
  "range": {
    "start": "2026-10-26",
    "end": "2026-10-26",
    "granularity": "day"
  },
  "data_until": "2026-10-26",
  "daily": [
    {
      "date": "2026-10-26",
      "searches": 41,
      "zero_result": 4,
      "errors": 0,
      "latency_sum": 16800,
      "ok_count": 41
    }
  ],
  "top_queries": [
    { "query": "新能源汽车销量预测", "count": 32 },
    { "query": "氢能产业园", "count": 21 },
    { "query": "储能装机量", "count": 18 }
  ],
  "selected": [
    { "query": "储能", "count": 41 }
  ],
  "totals": {
    "searches": 41,
    "zero_result": 4,
    "errors": 0,
    "zero_result_rate": 0.0976,
    "latency_sum": 16800,
    "ok_count": 41,
    "avg_latency_ms": 410
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `range` | 请求解析后的区间和粒度 |
| `data_until` | `search_daily` 最新一天，空表为 `null` |
| `daily[]` | 按粒度聚合的桶，`date` 是桶起点 |
| `top_queries[]` | 按日期和 `kind` 的 Top 词 |
| `selected[]` | 请求的 `queries` 各自数量，没命中给 0 |
| `totals` | 当前过滤条件下的合计与比例 |

口径：

- 只统计 `page=1`，翻页不重复计数。日期和桶按 `Asia/Shanghai` 切分。
- `zero_result` 和 `errors` 都是 `searches` 的子集。
- `queries` 只影响 `daily`、`selected` 和 `totals`，不影响 `top_queries`；所以 `top_queries` 的数量可以大于过滤后的 `totals`。`top_queries` 是全站口径，可能包含其他用户的检索词。
- `daily` 在区间末端与 `data_until` 中较早处停止；周、月桶的 `date` 可能早于 `start`。
- `latency_sum` 和 `ok_count` 可以按桶相加；不要对 `avg_latency_ms` 求平均。

`start > end`、跨度超过 366 天、`queries` 超过 20 个时返回 `422`。数据库不可用返回 `503`。

## 维护

`search_daily` 由下面的命令写入，每天运行一次：

```bash
python -m app.searchlog.rollup
```

首次上线先跑 `python -m app.searchlog.rollup --backfill`。

MCP 提供 `report_stats()` 和 `search_stats()`，参数与接口一致。
