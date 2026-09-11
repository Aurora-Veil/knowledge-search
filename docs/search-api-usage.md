# 知识图谱搜索 API 使用文档

```bash
pip install -r requirements.txt
python run.py
```

`run.py` 等价于 `uvicorn app.main:app --reload`。
服务地址 `http://127.0.0.1:8000`，交互文档 `http://127.0.0.1:8000/docs`。
示例中的 `$API` 代表 `http://127.0.0.1:8000/api/v1`。

## 1. 端点总览

| 方法 | 路径 | 用途 | `project_id` |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | 健康检查 | 无 |
| POST | `/api/v1/search` | 搜索，全文加筛选 | 缺省为全部项目 |
| GET | `/api/v1/objects/{object_type}/{oirf_id}` | 取完整对象 | 必填 |
| GET | `/api/v1/associations/{object_type}/{oirf_id}` | 取关联子图，含节点与边 | 必填 |
| GET | `/api/v1/projects` | 列出项目与各类对象数量 | 无 |

`object_type` 取值 `source`、`evidence`、`viewpoint`。典型用法是先 `/search` 定位对象，再用 `/objects` 取全文、用 `/associations` 取上下文。

## 2. 搜索 `POST /api/v1/search`

请求体为 JSON，字段全部可选。各参数对哪类对象生效见 2.4。

### 2.1 请求字段

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `q` | string | 无 | 全文检索词。空或缺省时只做筛选 |
| `type` | `source` / `evidence` / `viewpoint` / `all` | `all` | 搜哪类对象 |
| `mode` | `or` / `and` / `phrase` | `or` | 全文匹配松紧，只对 `q` 生效 |
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
| `size` | int | `20` | 每页条数，最大 `100` |
| `highlight` | bool | `true` | 是否返回高亮 `<em>…</em>` |

`q` 匹配的字段只有这些：

| type | 检索字段 |
| --- | --- |
| source | `identity.name`、`presentation.title`、`presentation.publisher` |
| evidence | `identity.name`、`presentation.subject`、`presentation.indicator`、`presentation.value`、`experience.original_publish` |
| viewpoint | `presentation.name`、`identity.name`、`experience.name` |

### 2.2 `mode`：召回松紧

| 值 | 含义 |
| --- | --- |
| `or` | 任一词命中即可，默认 |
| `and` | 所有词都要命中，顺序不限 |
| `phrase` | 所有词必须相邻出现 |

同一批查询词在三种模式下返回的条数如下。判断是否真的搜到要用 `mode=and`，`or` 会把只命中半个词的也算上。

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

`type=all` 时按此表判断每个参数对哪类对象生效。`生效` 表示参数参与过滤；`忽略` 表示该类对象没有这个字段，参数被忽略、该类照常返回；`排除` 表示该类对象不适用，直接不出结果。

| 参数 | source | evidence | viewpoint |
| --- | :--: | :--: | :--: |
| `status`、`presentation_type`、`responsible_role`、`project_id` | 生效 | 生效 | 生效 |
| `period`、`region`、`industry`、`source_type` | 忽略 | 生效 | 忽略 |
| `confidence_level` | 生效 | 生效 | 忽略 |
| `claim_type`、`applicable_scenario`、`cross_validation_mode` | 忽略 | 忽略 | 生效 |
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
  "total": 15, "page": 1, "size": 3,
  "hits": [
    {
      "id": "6a9fbd1b270db0c081be679d",  // ObjectId 字符串，全局唯一
      "object_type": "evidence", "project_id": 1,
      "oirf_id": "evidence:E028",        // 项目内唯一
      "score": 28.29,                    // 相关度分；type=all 时归一到 0~1，便于跨类型比较
      "raw_score": 28.29,                // 原始 BM25 分
      "identity": { "name": "…", "object_type": "evidence", "status": "PENDING" },
      "presentation": { "subject": "苹果", "value": "…", "period": "2024", "region": "全球" },
      "reasoning": { "source_ids": ["source:S005"] },
      "experience": { "confidence_level": "low", "original_publish": "澎湃新闻" },
      "responsibility": [ { "operation": "create", "operator": { "role": "analyst" } } ],
      "highlight": { "identity.name": ["<em>空间</em><em>计算</em>时代"] }
    }
  ]
}
```

响应只含卡片字段，长文本如 `presentation.content`、`presentation.explanation`、`presentation.raw_texts`、`presentation.summary`、`reasoning.narrative`、`*_reason`、`lifecycle` 需用 `/objects` 取。

### 2.7 注意

- 数组类参数 `project_id`、`source_type`、`publisher`、`source_ids`、`evidence_ids` 传 `[]` 表示不设限；标量参数传 `[]` 返回 `422`。
- `project_id` 不传或传 `[]` 表示全部项目；`project_id: 0` 是有效值，返回 0 条，不等于全部。
- 纯筛选请求的 `score` 与 `raw_score` 恒为 `0`，`highlight` 也为空，都属正常。
- `inner_hits` 只在按 `responsible_role`、`source_ids`、`evidence_ids` 过滤时出现，用来标识命中的是哪条责任链、哪一步推理。
- 跨项目结果里 `oirf_id` 会重号，识别对象用全局唯一的 `id`，或用 `project_id` 加 `oirf_id`。

## 3. 完整对象 `GET /api/v1/objects/{object_type}/{oirf_id}`

取完整对象，含 `/search` 卡片里没有的长文本。`object_type` 与 `oirf_id` 放在路径上，如 `/objects/viewpoint/viewpoint:V001`；`project_id` 是必填查询参数，缺省返回 `422`，因为 `oirf_id` 只在项目内唯一。

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


## 6. 错误码

| 状态码 | 场景 | 响应 |
| --- | --- | --- |
| `400` | `/objects` 的 `object_type` 非法 | `{"detail":"unknown object_type: …"}` |
| `404` | `/objects` 找不到对象，或 `project_id` 指向没有数据的项目 | `{"detail":"object not found"}` |
| `404` | `/associations` 找不到对象 | `{"detail":"viewpoint 'viewpoint:V999' not found in project 1"}` |
| `422` | 参数校验失败：类型不对、超出范围、缺必填、`mode`/`direction`/`include` 取值非法、标量参数传了数组 | FastAPI 字段级错误 |
| `422` | `/associations` 的 `oirf_id` 前缀与 `object_type` 不一致 | `{"detail":"oirf_id prefix must match object_type: …"}` |


