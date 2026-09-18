# 知识图谱搜索 API 使用文档

```bash
pip install -r requirements.txt

python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-base-zh-v1.5', cache_dir='.hf-cache/hub')"

python run.py
```

`run.py` 等价于 `uvicorn app.main:app --reload`。
服务地址 `http://127.0.0.1:8000`，交互文档 `http://127.0.0.1:8000/docs`。
示例中的 `$API` 代表 `http://127.0.0.1:8000/api/v1`。

启动后会在后台预热向量模型，约 15 秒。

## 1. 端点总览

| 方法 | 路径 | 用途 | `project_id` |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | 健康检查 | 无 |
| POST | `/api/v1/search` | 搜索，词法加向量再加筛选 | 缺省为全部项目 |
| GET | `/api/v1/objects/{object_type}/{oirf_id}` | 取完整对象 | 必填 |
| GET | `/api/v1/associations/{object_type}/{oirf_id}` | 取关联子图，含节点与边 | 必填 |
| GET | `/api/v1/projects` | 列出项目与各类对象数量 | 无 |
| POST | `/api/v1/reports/search` | 报告检索，词法加向量再加筛选 | 无 |
| GET | `/api/v1/reports/{report_id}` | 取报告详情，含摘要 | 无 |

`object_type` 取值 `source`、`evidence`、`viewpoint`。典型用法是先 `/search` 定位对象，再用 `/objects` 取全文、用 `/associations` 取上下文。

报告是另一份数据集，与这三类对象无关。

## 2. 搜索 `POST /api/v1/search`

请求体为 JSON，字段全部可选。各参数对哪类对象生效见 2.4。

### 2.1 请求字段

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `q` | string | 无 | 检索词。同时走词法与向量两路；空或缺省时只做筛选、不走向量 |
| `type` | `source` / `evidence` / `viewpoint` / `all` | `all` | 搜哪类对象 |
| `mode` | `or` / `and` / `phrase` | `or` | 全文匹配松紧，只对 `q` 的词法一路生效 |
| `project_id` | int \| int[] | 无 | 单值为单个项目，数组为多项目并集，不传或 `[]` 为全部项目 |
| `status` | string | 无 | `identity.status` |
| `presentation_type` | string | 无 | `presentation.type` |
| `period` | string | 无 | 时期 |
| `region` | string | 无 | 地区 |
| `industry` | string | 无 | 行业 |
| `source_type` | string \| string[] | 无 | 来源类型 |
| `publisher` | string \| string[] | 无 | 来源方 |
| `confidence_level` | string | 无 | 置信度 |
| `claim_type` | string | 无 | 判断类型 |
| `applicable_scenario` | string | 无 | 适用场景 |
| `cross_validation_mode` | string | 无 | 交叉验证方式 |
| `responsible_role` | string | 无 | 职责角色 |
| `source_ids` | string[] | 无 | 引用溯源：返回引用了某材料的对象 |
| `evidence_ids` | string[] | 无 | 引用溯源：返回引用了某证据的对象 |
| `page` | int | `1` | 页码，从 1 起 |
| `size` | int | `20` | 每页条数，最大 `100`；且 `page`×`size` 不得超过 `200`，超出返回 `400` |
| `highlight` | bool | `true` | 是否返回高亮 `<em>…</em>` |

`q` 的**词法**一路匹配的字段只有这些：

| type | 检索字段 |
| --- | --- |
| source | `identity.name`、`presentation.title`、`presentation.publisher` |
| evidence | `identity.name`、`presentation.subject`、`presentation.indicator`、`presentation.value`、`experience.original_publish` |
| viewpoint | `presentation.name`、`identity.name`、`experience.name` |

`q` 还会并行走一次**向量**检索，比对的是每个实体的整篇拼接文本，不是上表这些字段。所以词法零命中时仍可能返回结果，`total` 与 `hits` 会不一致。

### 2.2 `mode`：召回松紧

| 值 | 含义 |
| --- | --- |
| `or` | 任一词命中即可，默认 |
| `and` | 所有词都要命中，顺序不限 |
| `phrase` | 所有词必须相邻出现 |

同一批查询词在三种模式下的 `total` 如下。判断是否真的搜到要用 `mode=and`，`or` 会把只命中半个词的也算上。`total` 只统计词法命中，所以 `and` 下的 `0` 只代表词法零命中，`hits` 仍可能由向量分支填充。

| `q` | `or` | `and` | `phrase` |
| --- | --- | --- | --- |
| `空间计算` | 23 | 13 | 12 |
| `空间计算设备` | 73 | 8 | 8 |
| `zzz不存在词 空间计算` | 23 | 0 | 0 |

### 2.3 筛选取值

`publisher` 的取值取决于实际入库数据，此处不枚举。其余筛选取值如下：

| 参数 | 取值 |
| --- | --- |
| `status` | `PENDING` |
| `region` | `全球`、`中国` |
| `source_type` | `secondary_public`、`analyst_calculation` |
| `industry` | `空间计算设备` |
| `period` | `2023`、`2024`、`2022`、`2021`、`2020`、`2019`、`2018`、`2013`、`2001`、`2027`、`2023-2027` |
| `confidence_level` | `medium`、`low` |
| `claim_type` | `事实判断`、`因果判断`、`测算判断`、`趋势判断`、`预测判断` |
| `applicable_scenario` | `industry_research` |
| `cross_validation_mode` | `不同原始信源相互印证`、`不同方法或不同数据体系交叉验证`、`无需验证` |
| `responsible_role` | `analyst` |
| `presentation_type` · evidence | `历史值`、`计算值`、`预估值`、`规则值` |
| `presentation_type` · viewpoint | `趋势判断`、`行业判断`、`因果判断`、`产业链层面`、`预测判断`、`企业评估` |

`period` 是精确串匹配：`period=2024` 匹配不到区间值 `2023-2027`。

### 2.4 参数适用类型

`type=all` 时按此表判断每个参数对哪类对象生效。`生效` 表示参数参与过滤；`排除` 表示该类对象不适用，直接不出结果。

| 参数 | source | evidence | viewpoint |
| --- | :--: | :--: | :--: |
| `status`、`presentation_type`、`responsible_role`、`project_id` | 生效 | 生效 | 生效 |
| `period`、`region`、`industry`、`source_type` | 排除 | 生效 | 排除 |
| `confidence_level` | 生效 | 生效 | 排除 |
| `claim_type`、`applicable_scenario`、`cross_validation_mode` | 排除 | 排除 | 生效 |
| `publisher` | 生效 | 生效 | 排除 |
| `source_ids` | 排除 | 生效 | 生效 |
| `evidence_ids` | 排除 | 排除 | 生效 |

### 2.5 示例

```bash
# 全文加多项筛选
curl -s -X POST $API/search -H "Content-Type: application/json" \
  -d '{"q":"空间计算","type":"evidence","project_id":1,"industry":"空间计算设备","size":3}'

# 收紧召回：73 条变 8 条
curl -s -X POST $API/search -H "Content-Type: application/json" \
  -d '{"q":"空间计算设备","type":"all","mode":"and"}'

# 只看来自澎湃新闻的材料，2 条
curl -s -X POST $API/search -H "Content-Type: application/json" \
  -d '{"publisher":"澎湃新闻"}'

# 多个来源取并集，24 条
curl -s -X POST $API/search -H "Content-Type: application/json" \
  -d '{"publisher":["知乎","知乎专栏"]}'

# 来源与内容同时限定，2 条
curl -s -X POST $API/search -H "Content-Type: application/json" \
  -d '{"q":"空间计算","publisher":"澎湃新闻"}'

# 多项目取并集
curl -s -X POST $API/search -H "Content-Type: application/json" \
  -d '{"q":"空间计算","type":"all","project_id":[1,2]}'

# 引用溯源：谁引用了这份材料，179 条
curl -s -X POST $API/search -H "Content-Type: application/json" \
  -d '{"type":"all","project_id":1,"source_ids":["source:S001"]}'

# 引用溯源：同一步内同时引用该材料与该证据，1 条
curl -s -X POST $API/search -H "Content-Type: application/json" \
  -d '{"type":"viewpoint","project_id":1,"source_ids":["source:S002"],"evidence_ids":["evidence:E005"]}'
```

### 2.6 响应

```jsonc
{
  "total": 23, "page": 1, "size": 3,
  "hits": [
    {
      "id": "6a9fbd1b270db0c081be679d",  // ObjectId 字符串，全局唯一
      "object_type": "evidence", "project_id": 1,
      "oirf_id": "evidence:E028",        // 项目内唯一
      "score": 0.03252,                  // RRF 名次分
      "raw_score": 25.5993,              // BM25
      "identity": { "name": "…", "object_type": "evidence", "status": "PENDING" },
      "presentation": { "subject": "苹果", "value": "…", "period": "2024", "region": "全球" },
      "reasoning": { "source_ids": ["source:S005"] },
      "experience": { "confidence_level": "low", "original_publish": "澎湃新闻" },
      "responsibility": [ { "operation": "create", "operator": { "role": "analyst" } } ],
      "highlight": { "identity.name": ["<em>空间</em><em>计算</em>时代"] },
      "knn_score": 0.74834895,           // 向量相似度
      "match_source": "both"             // bm25 / knn / both，哪几路召回了它
    }
  ]
}
```

三个分数含义不同，都不要跨查询比较：`score` 由名次算出（量级 `0.016`~`0.033`），`raw_score` 是 BM25（无上界，随查询漂移），`knn_score` 是余弦映射到 `[0,1]`。

响应只含卡片字段，长文本如 `presentation.content`、`presentation.explanation`、`presentation.raw_texts`、`presentation.summary`、`reasoning.narrative`、`*_reason`、`lifecycle` 需用 `/objects` 取。

## 3. 完整对象 `GET /api/v1/objects/{object_type}/{oirf_id}`

取完整对象，含 `/search` 卡片里没有的长文本。`object_type` 与 `oirf_id` 放在路径上，如 `/objects/viewpoint/viewpoint:V001`

`project_id` 是必填查询参数，缺省返回 `422`，因为 `oirf_id` 只在项目内唯一

```bash
curl "$API/objects/viewpoint/viewpoint:V001?project_id=1"
```

响应为完整对象，含 `id`、`oirf_id`、`project_id`、`identity`、`presentation`、`reasoning`、`experience`、`responsibility`、`lifecycle`。

## 4. 关联图谱 `GET /api/v1/associations/{object_type}/{oirf_id}`

取从一个对象出发的关联子图。

| 参数 | 位置 | 默认 | 说明 |
| --- | --- | --- | --- |
| `object_type` | path | 无 | 必须与 `oirf_id` 前缀一致，否则 `422` |
| `oirf_id` | path | 无 | 如 `viewpoint:V001` |
| `project_id` | query | 必填 | 不传返回 `422` |
| `hops` | query | `1` | 跳数，取 `1` 或 `2` |
| `direction` | query | `both` | `out` 为观点到证据到材料，`in` 为谁引用了它，`both` 为两者 |
| `types` | query | 全部 | 逗号分隔，如 `evidence,source`。只筛返回的类型，不影响展开 |
| `include` | query | `card` | `card` 给完整卡片，`ref` 只给 `id`、`oirf_id`、`object_type`、`project_id`、`identity.{name,status}` |
| `limit` | query | `50` | 每个 `direction` 与 `type` 组合的桶的上限，最大 `200` |

```bash
# 一个观点的证据与来源，10 节点 / 11 边
curl "$API/associations/viewpoint/viewpoint:V001?project_id=1&direction=out"

# 一份材料被谁用了，179 节点：160 证据加 19 观点
curl "$API/associations/source/source:S001?project_id=1&direction=in&limit=200"

# 只要引用它的观点，跳过证据，19 节点
curl "$API/associations/source/source:S001?project_id=1&direction=in&types=viewpoint"

# 一条证据的上下文：它的来源加引用它的观点，2 节点
curl "$API/associations/evidence/evidence:E005?project_id=1"
```

```jsonc
{
  "root":  { "id": "…", "oirf_id": "viewpoint:V001", "object_type": "viewpoint", "identity": { … } },
  "project_id": 1, "hops": 1, "direction": "out", "include": "card",
  "nodes": [ { "oirf_id": "evidence:E005", "object_type": "evidence", "identity": { … }, … } ],
  "edges": [ { "from": "viewpoint:V001", "to": "evidence:E005", "rel": "step_evidence",
               "step": 0, "hop": 1, "label": "全球与中国2023年前三季度VR/AR出货量…" } ],
  "truncated": [],   // 被截断的桶，如 ["in:evidence"]
  "missing": []      // 被引用但取不到文档的 oirf_id
}
```

`rel` 取 `step_evidence`、`step_source`、`evidence_source`；`step` 是第几步推理，`evidence_source` 时为 `null`；`label` 是该步的推理文本。

注意：

- 结构性恒空：`viewpoint` 没有入边，`direction=in` 返回 0 条；`source` 没有出边，`direction=out` 返回 0 条。
- `truncated` 是桶列表，`[]` 表示没截断。`limit=50` 时 `source:S001&direction=in` 会截到 `["in:evidence"]`，返回 50 条证据加全部 19 个观点。
- 节点没有 `score`。
- 同一对节点可能有多条边，分别对应不同 `step`，所以边数可能大于节点对数。

## 5. 项目列表 `GET /api/v1/projects`

列出库里有哪几个 `project_id`，以及每个项目三类对象的数量。无参数。

```bash
curl "$API/projects"
```

```jsonc
{
  "projects": [
    { "project_id": 1, "source": 24, "evidence": 349, "viewpoint": 24 }
  ],
  "total_objects": 397
}
```

## 6. 报告检索

报告是独立数据集，与上面三类对象无关，检索方式与 `/search` 一致：`q` 并行走词法 + 向量两路召回，RRF 融合后排序。

`q` 的**词法**一路只匹配三个字段：

| 字段 | 权重 |
| --- | --- |
| `title` | 3 |
| `industry.text` | 2 |
| `summary` | 1 |

`q` 还会并行走一次**向量**检索，比对的向量文本是 `title + summary`，不是上表这三个字段。所以词法零命中时仍可能返回结果，`total` 与 `hits` 会不一致。

`mode` 与 `/search` 同义：`or` 任一词命中，`and` 所有词都要命中，`phrase` 所有词必须相邻。

`time_weight` 控制时间衰减：默认为 `0`，大于 `0` 时两条召回分支都按 `原分 × (1 - w + w × 新鲜度)` 重排，新鲜度由 `publish_date` 算，半衰期 1 年、前 3 个月不扣分。它只改排序不改命中文档。

### 6.1 检索 `POST /api/v1/reports/search`

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `q` | string | 必填 | 检索词；词法与向量两路召回，写自然语言问句或堆关键词都可以 |
| `mode` | `or` / `and` / `phrase` | `or` | 词法一路的召回松紧 |
| `time_weight` | float | `0` | 时间衰减权重，`0` 关闭；越大越偏向新报告 |
| `report_id` | string[] | 无 | 精确匹配，已知 id 时用来批量取卡片 |
| `layout` | `横版` / `竖版` | 无 | 版式，精确匹配 |
| `industry` | string[] | 无 | 行业，精确匹配，取值为完整行业名 |
| `publish_date_from` / `publish_date_to` | date | 无 | `YYYY-MM-DD`，闭区间 |
| `page` | int | `1` | 页码，从 1 起；`page`×`size` 上限 `200` |
| `size` | int | `20` | 每页条数，最大 `100` |
| `highlight` | bool | `true` | 关掉则响应里没有 `highlight` |

```bash
# 检索加筛选，3 条
curl -s -X POST $API/reports/search -H "Content-Type: application/json" \
  -d '{"q":"氢能产业园发展格局","layout":"横版","size":3}'

# 收紧词法召回
curl -s -X POST $API/reports/search -H "Content-Type: application/json" \
  -d '{"q":"新能源汽车销量预测","mode":"and"}'

# 只要 2025 年之后发布的
curl -s -X POST $API/reports/search -H "Content-Type: application/json" \
  -d '{"q":"新能源汽车销量预测","publish_date_from":"2025-01-01"}'

# 排序偏向新报告
curl -s -X POST $API/reports/search -H "Content-Type: application/json" \
  -d '{"q":"新能源汽车销量预测","time_weight":0.2}'
```

```jsonc
{
  "total": 9,                                      // 只是词法分支的命中数，不含向量分支
  "page": 1,
  "size": 3,
  "hits": [
    {
      "report_id": "62e33fbc2f669532f23e1cd8", 
      "title": "2022年中国氢能产业园研究报告：…",
      "industry": [], "layout": "横版",
      "publish_date": "2022-07-29",
      "url": "https://www.leadleo.com/report/reading/62e33fbc2f669532f23e1cd8",
      "score": 0.0325,                             // RRF 融合分
      "raw_score": 12.4,                           // BM25，词法没命中时为 null
      "knn_score": 0.8123,                         // 向量分，值域 (1 + cos) / 2
      "match_source": "both",                      // bm25 / knn / both
      "highlight": { "title": ["<em>氢能</em>产业园…"] }
    }
  ]
}
```

`total` 与 `/search` 一样只统计词法命中，所以它可能小于返回条数。列表只给卡片，不含 `summary`。

### 6.2 详情 `GET /api/v1/reports/{report_id}`

```bash
curl "$API/reports/62e33fbc2f669532f23e1cd8"
```

字段与列表相同，多一个 `summary`、少 `score` / `raw_score` / `knn_score` / `match_source` / `highlight`。`report_id` 不存在返回 `404`。

## 7. 错误码

| 状态码 | 场景 | 响应 |
| --- | --- | --- |
| `400` | `/objects` 的 `object_type` 非法 | `{"detail":"unknown object_type: …"}` |
| `400` | `/search` 的 `page`×`size` 超过 `200` | `{"detail":"page*size = 220 exceeds RESULT_WINDOW = 200; …"}` |
| `400` | `/reports/search` 的 `q` 是空白串 | `{"detail":"q is required: reports search needs a query"}` |
| `400` | `/reports/search` 的 `page`×`size` 超过 `200` | `{"detail":"page*size = 220 exceeds RESULT_WINDOW = 200; …"}` |
| `404` | `/objects` 找不到对象，或 `project_id` 指向没有数据的项目 | `{"detail":"object not found"}` |
| `404` | `/associations` 找不到对象 | `{"detail":"viewpoint 'viewpoint:V999' not found in project 1"}` |
| `404` | `/reports/{report_id}` 找不到报告 | `{"detail":"report not found: …"}` |
| `422` | 参数校验失败：类型不对、超出范围、缺必填、`mode`/`direction`/`include` 取值非法、标量参数传了数组 | FastAPI 字段级错误 |
| `422` | `/associations` 的 `oirf_id` 前缀与 `object_type` 不一致 | `{"detail":"oirf_id prefix must match object_type: …"}` |
