# 知识图谱搜索 API 使用文档

```bash
pip install -r requirements.txt
python run.py                      # 等价 uvicorn app.main:app --reload
```

- 服务地址：`http://127.0.0.1:8000`
- OpenAPI 交互页：`http://127.0.0.1:8000/docs`

---

## 1. 端点总览

| 方法 | 路径 | 用途 | `project_id` |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | 健康检查 | — |
| POST | `/api/v1/search` | 搜索（全文 + 筛选） | 缺省 = 全部项目 |
| GET | `/api/v1/objects/{object_type}/{oirf_id}` | 取**完整**对象 | 必填 |
| GET | `/api/v1/associations/{object_type}/{oirf_id}` | 取关联子图（节点 + 边） | 必填 |

`object_type` ∈ `source` / `evidence` / `viewpoint`。

---

## 2. 搜索 `POST /api/v1/search`

请求体 JSON，字段全部可选。

### 2.1 请求字段

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `q` | string | 无 | 全文检索词。空/缺省 = 只做筛选 |
| `type` | `source` / `evidence` / `viewpoint` / `all` | `all` | 搜哪类对象 |
| `mode` | `or` / `and` / `phrase` | `or` | 全文匹配松紧，只对 `q` 生效 |
| `project_id` | int \| int[] | 无 | 单值 = 单个项目；数组 = 多项目并集；不传或 `[]` = **全部项目** |
| `status` | string | 无 | `identity.status` |
| `presentation_type` | string | 无 | `presentation.type` |
| `period` | string | 无 | 时期（仅 evidence） |
| `region` | string | 无 | 地区（仅 evidence） |
| `industry` | string | 无 | 行业（仅 evidence） |
| `source_type` | string \| string[] | 无 | 来源类型（仅 evidence） |
| `publisher` | string \| string[] | 无 | 来源/出版方 |
| `confidence_level` | string | 无 | 置信度（仅 source / evidence） |
| `claim_type` | string | 无 | 判断类型（仅 viewpoint） |
| `applicable_scenario` | string | 无 | 适用场景（仅 viewpoint） |
| `cross_validation_mode` | string | 无 | 交叉验证方式（仅 viewpoint） |
| `responsible_role` | string | 无 | 职责角色（三类通用） |
| `source_ids` | string[] | 无 | 引用溯源：引用了某**材料**的对象 |
| `evidence_ids` | string[] | 无 | 引用溯源：引用了某**证据**的对象 |
| `page` | int | `1` | 页码，从 1 起 |
| `size` | int | `20` | 每页条数，最大 `100` |
| `highlight` | bool | `true` | 是否返回高亮 `<em>…</em>` |

`q` 匹配的字段（只有这些）：

| type | 检索字段 |
| --- | --- |
| source | `identity.name`、`presentation.title`、`presentation.publisher` |
| evidence | `identity.name`、`presentation.subject`、`presentation.indicator`、`presentation.value`、`experience.original_publish` |
| viewpoint | `presentation.name`、`identity.name`、`experience.name` |

### 2.2 `mode`：召回松紧

| 值 | 含义 |
| --- | --- |
| `or`（默认） | 任一词命中即可 |
| `and` | 所有词都要命中，顺序不限 |
| `phrase` | 所有词必须相邻出现 |

以 `type=all` 为例，同一批查询词三种模式的返回条数：

| `q` | `or` | `and` | `phrase` |
| --- | --- | --- | --- |
| `空间计算` | 23 | 13 | 12 |
| `空间计算设备` | 73 | 8 | 8 |
| `zzz不存在词 空间计算` | 23 | 0 | 0 |

> 要判断"是否真的搜到"，用 `mode=and`：`or` 会把只命中半个词的也算上。

### 2.3 筛选取值

**`publisher` 取值**：依据实际情况

**其他取值**：依据目前有的，如下

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
| `presentation_type` (evidence) | `历史值`、`计算值`、`预估值`、`规则值` |
| `presentation_type` (viewpoint) | `趋势判断`、`行业判断`、`因果判断`、`产业链层面`、`预测判断`、`企业评估` |

> `period` 是**精确串**匹配：`period=2024` 匹配不到区间值 `2023-2027`。

### 2.4 参数适用类型

`type=all` 时按此表判断各参数对哪类对象生效。

**✅** 生效 　
**—** 该类无此字段：**忽略该参数、照常返回** 
**⛔** 该类不适用：**直接不出结果**

| 参数 | source | evidence | viewpoint |
| --- | :--: | :--: | :--: |
| `status`、`presentation_type`、`responsible_role` | ✅ | ✅ | ✅ |
| `project_id` | ✅ | ✅ | ✅ |
| `period`、`region`、`industry`、`source_type` | — | ✅ | — |
| `confidence_level` | ✅ | ✅ | — |
| `claim_type`、`applicable_scenario`、`cross_validation_mode` | — | — | ✅ |
| `publisher` | ✅ | ✅ | ⛔ |
| `source_ids` | ⛔ | ✅ | ✅ |
| `evidence_ids` | ⛔ | ⛔ | ✅ |

### 2.5 示例

```bash
# 全文 + 多项筛选
curl -s -X POST http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" \
  -d '{"q":"空间计算","type":"evidence","project_id":1,"industry":"空间计算设备","size":3}'

# 收紧召回：73 条 → 8 条
curl -s -X POST http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" \
  -d '{"q":"空间计算设备","type":"all","mode":"and"}'

# 只看来自澎湃新闻的材料（2 条）
curl -s -X POST http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" \
  -d '{"publisher":"澎湃新闻"}'

# 来自澎湃新闻 且 内容讲空间计算（2 条）
curl -s -X POST http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" \
  -d '{"q":"空间计算","publisher":"澎湃新闻"}'

# 多个来源并集（24 条）
curl -s -X POST http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" \
  -d '{"publisher":["知乎","知乎专栏"]}'

# 引用溯源：谁引用了这份材料（179 条）
curl -s -X POST http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" \
  -d '{"type":"all","project_id":1,"source_ids":["source:S001"]}'

# 引用溯源（同一步内同时引用该材料与该证据，1 条）
curl -s -X POST http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" \
  -d '{"type":"viewpoint","project_id":1,"source_ids":["source:S002"],"evidence_ids":["evidence:E005"]}'

# 多项目并集
curl -s -X POST http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" \
  -d '{"q":"空间计算","type":"all","project_id":[1,2]}'
```

### 2.6 响应

```jsonc
{
  "total": 15, "page": 1, "size": 3,
  "hits": [
    {
      "id": "6a9fbd1b270db0c081be679d",  // ObjectId 字符串，全局唯一
      "object_type": "evidence",
      "project_id": 1,
      "oirf_id": "evidence:E028",        // 项目内唯一
      "score": 28.29,                    // 相关度分（type=all 时统一到 0~1，便于跨类型比较）
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

响应只含卡片字段。长文本（`presentation.content`/`explanation`/`raw_texts`/`summary`、`reasoning.narrative`、`*_reason`、`lifecycle`）用 `/objects` 取。

### 2.7 注意

- 数组类参数（`project_id`、`source_type`、`publisher`、`source_ids`、`evidence_ids`）传 `[]` = **不设限**；标量参数传 `[]` → **422**。
- `project_id` 不传或 `[]` = 全部项目；`project_id: 0` 是一个**有效值**（返回 0 条），不是"全部"。
- 纯筛选请求（`q` 为空）的 `score` / `raw_score` 恒为 `0`，正常。
- `highlight` 只在 `q` 非空时有内容。
- `inner_hits` 只在按 `responsible_role` / `source_ids` / `evidence_ids` 过滤时出现，标识命中的是哪条责任链 / 哪一步推理。
- 跨项目结果里 **`oirf_id` 会重号**：列表 key 和点详情都用 `id`（全局唯一），或 `project_id` + `oirf_id`。

---

## 3. 完整对象 `GET /api/v1/objects/{object_type}/{oirf_id}`

取完整对象（含 `/search` 卡片里没有的长文本）。

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| `object_type` | path | ✅ | `source` / `evidence` / `viewpoint` |
| `oirf_id` | path | ✅ | 如 `viewpoint:V001` |
| `project_id` | query | ✅ | 不传 → **422** |

```bash
curl "http://127.0.0.1:8000/api/v1/objects/viewpoint/viewpoint:V001?project_id=1"
```

响应：完整对象原样返回（`id`、`oirf_id`、`project_id`、`identity`、`presentation`、`reasoning`、`experience`、`responsibility`、`lifecycle`）。

---

## 4. 关联图谱 `GET /api/v1/associations/{object_type}/{oirf_id}`

取从一个对象出发的关联子图。

| 参数 | 位置 | 默认 | 说明 |
| --- | --- | --- | --- |
| `object_type` | path | — | 必须与 `oirf_id` 前缀一致，否则 422 |
| `oirf_id` | path | — | 如 `viewpoint:V001` |
| `project_id` | query | **必填** | 不传 → 422 |
| `hops` | query | `1` | 跳数 1 or 2 |
| `direction` | query | `both` | `out` = 观点→证据→材料；`in` = 谁引用了它；`both` = 两者 |
| `types` | query | 全部 | 逗号分隔，如 `evidence,source`。只筛返回的类型，不影响展开 |
| `include` | query | `card` | `card` = 完整卡片；`ref` = 只给 `id`/`oirf_id`/`object_type`/`project_id`/`identity.{name,status}` |
| `limit` | query | `50` | **每个 `(direction, type)` 桶**的上限，最大 `200` |

```bash
# 一个观点的证据与来源（10 节点 / 11 边）
curl "http://127.0.0.1:8000/api/v1/associations/viewpoint/viewpoint:V001?project_id=1&direction=out"

# 一份材料被谁用了（179 节点：160 证据 + 19 观点）
curl "http://127.0.0.1:8000/api/v1/associations/source/source:S001?project_id=1&direction=in&limit=200"

# 只要引用它的观点，跳过证据（19 节点）
curl "http://127.0.0.1:8000/api/v1/associations/source/source:S001?project_id=1&direction=in&types=viewpoint"

# 一条证据的上下文：它的来源 + 引用它的观点（2 节点）
curl "http://127.0.0.1:8000/api/v1/associations/evidence/evidence:E005?project_id=1"
```

```jsonc
{
  "root":  { "id": "…", "oirf_id": "viewpoint:V001", "object_type": "viewpoint", "identity": { … } },
  "project_id": 1, "hops": 1, "direction": "out", "include": "card",
  "nodes": [ { "oirf_id": "evidence:E005", "object_type": "evidence", "identity": { … }, … } ],
  "edges": [ {
      "from": "viewpoint:V001", "to": "evidence:E005",
      "rel": "step_evidence",   // step_evidence | step_source | evidence_source
      "step": 0,                // 第几步推理（evidence_source 时为 null）
      "hop": 1,                 // 第几跳
      "label": "全球与中国2023年前三季度VR/AR出货量…"   // 该步的推理文本
  } ],
  "truncated": [],              // 被截断的桶，如 ["in:evidence"]
  "missing": []                 // 被引用但取不到文档的 oirf_id
}
```

注意：

- **结构性恒空**：`viewpoint` 没有入边 → `direction=in` 返回 0 条；`source` 没有出边 → `direction=out` 返回 0 条。
- `truncated` 是**桶列表**，`[]` 表示没截断。`limit=50` 时 `source:S001&direction=in` 会截到 `["in:evidence"]`（返回 50 条证据 + 全部 19 个观点）。
- 节点**没有 `score`**。
- 同一对节点可能有多条边（不同 `step`），所以边数可能大于节点对数。

---

## 5. 错误码

| 状态码 | 场景 | 响应 |
| --- | --- | --- |
| `400` | `/objects` 的 `object_type` 非法 | `{"detail":"unknown object_type: …"}` |
| `404` | `/objects` 找不到对象（含 `project_id` 指向无数据的项目） | `{"detail":"object not found"}` |
| `404` | `/associations` 找不到对象 | `{"detail":"viewpoint 'viewpoint:V999' not found in project 1"}` |
| `422` | 参数校验失败：类型不对、超出范围、缺必填、`mode`/`direction`/`include` 取值非法、标量参数传了数组 | FastAPI 字段级错误 |
| `422` | `/associations` 的 `oirf_id` 前缀与 `object_type` 不一致 | `{"detail":"oirf_id prefix must match object_type: …"}` |

---

## 6. 常见错误用法

| 写法 | 现象 | 改为 |
| --- | --- | --- |
| `publisher=澎湃` | 0 条 | `publisher=澎湃新闻`（要完整值） |
| `publisher="Wind "` / `"wind"` | 0 条 | `publisher=Wind`（空格、大小写敏感） |
| 用 `q` 找来源 | 漏 + 假阳性多 | 用 `publisher` |
| `q=空间计算` 后直接判断"搜到了" | 23 条里含只命中"空间"或"计算"的 | 加 `"mode":"and"` → 13 条 |
| `type=viewpoint` + `publisher` | 0 条 | `publisher` 只对 source / evidence 生效 |
| `type=source` + `source_ids` | 0 条 | 去掉 `type=source`，或用 `type=all` |
| `type=evidence` + `evidence_ids` | 0 条 | 改用 `type=viewpoint` |
| `"project_id":[]` 以为会返回 0 条 | 返回**全部**项目 | 不设限就是全部；要 0 条用不存在的项目号 |
| `/objects` 不传 `project_id` | 422 | 必传 |
| `/associations` 不传 `project_id` | 422 | 必传 |
| `/associations/viewpoint/source:S001` | 422 | 前缀与 `object_type` 必须一致 |

---

