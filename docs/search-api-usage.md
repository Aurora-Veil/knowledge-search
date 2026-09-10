# 知识图谱搜索 API 使用文档

基于 MongoDB（权威数据）+ Elasticsearch（检索引擎）的搜索接口。
默认环境：MongoDB「knowledge_db」、Elasticsearch「knowledge_*」三索引（source / evidence / viewpoint）。

- 服务地址：`http://127.0.0.1:8000`
- OpenAPI 文档（自动生成）：`http://127.0.0.1:8000/docs`

## 1. 启动

```bash
pip install -r requirements.txt
python run.py            # 等价 uvicorn app.main:app --reload
```

## 2. 端点总览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/api/v1/health`          | 健康检查 |
| POST | `/api/v1/search`          | 统一搜索（全文 + 精确筛选 + 关联） |
| GET  | `/api/v1/objects/...`     | 按 oirf_id 取完整对象（回 Mongo） |

---

## 3. 统一搜索 `POST /api/v1/search`

### 3.1 请求体

JSON，字段均可选，缺省有默认值。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `q` | string | 无 | 全文检索词；空/缺省 = 仅精确筛选 |
| `type` | `source` / `evidence` / `viewpoint` / `all` | `all` | 要搜的对象类型 |
| `mode` | `or` / `and` / `phrase` | `or` | 全文匹配松紧（仅对 `q` 生效）：`or` 任一命中 / `and` 所有词都命中 / `phrase` 词必须相邻 |
| `project_id` | int | 无 | 限定**单个**项目；与 `project_ids` 互斥（同传返回 400） |
| `project_ids` | int[] | 无 | 限定**多个**项目（并集）；与 `project_id` 互斥，空数组返回 400 |
| `status` | string | 无 | 精确筛 `identity.status` |
| `presentation_type` | string | 无 | 精确筛 `presentation.type` |
| `period` | string | 无 | 精确筛 `presentation.period.keyword`（按精确串匹配） |
| `region` | string | 无 | 精确筛 `presentation.region`（仅 evidence） |
| `industry` | string | 无 | 精确筛 `presentation.industry`（仅 evidence） |
| `source_type` | string \| string[] | 无 | 精确筛 `presentation.source_type`（仅 evidence），单值或多值 |
| `confidence_level` | string | 无 | 精确筛 `experience.confidence_level`（仅 source/evidence；viewpoint 经验层无此字段） |
| `claim_type` | string | 无 | 精确筛 `experience.claim_type`（仅 viewpoint） |
| `applicable_scenario` | string | 无 | 精确筛 `experience.applicable_scenario`（仅 viewpoint） |
| `cross_validation_mode` | string | 无 | 精确筛 `experience.cross_validation_mode`（仅 viewpoint） |
| `responsible_role` | string | 无 | 职责（审计）筛：命中 `responsibility[].operator.role`（三类通用，nested） |
| `source_ids` | string[] | 无 | 关联（引用溯源）：引用某材料的对象。仅 **evidence**（扁平 `reasoning.source_ids`）/ **viewpoint**（步骤嵌套 `reasoning.steps.source_ids`） |
| `evidence_ids` | string[] | 无 | 关联（引用溯源）：引用某证据的对象。仅 **viewpoint**（步骤嵌套 `reasoning.steps.evidence_ids`） |
| `page` | int | `1` | 页码（从 1 起） |
| `size` | int | `20` | 每页条数（≤100） |
| `highlight` | bool | `true` | 是否返回命中高亮（`<em>…</em>`） |

### 3.2 说明

- **全文检索**：只对每类型的指定字段做加权匹配（见「4. 字段说明」）；`q` 为空时跳过全文。
- **`mode`（召回松紧）**：`q` 分词后要求命中多少才算命中——`or`（默认）任一命中即可；`and` 所有词都要命中（顺序不限）；`phrase` 词必须相邻出现。字段与权重三种模式完全一致，**只改召回、不改打分口径**。实测（`type=all`）：

  | `q` | `or`（默认） | `and` | `phrase` |
  |---|---|---|---|
  | `空间计算` | 23 | 13 | 12 |
  | `空间计算设备` | **73** | **8** | **8** |
  | `zzz不存在词 空间计算` | **23**（无关词被忽略） | **0** | **0** |

  > `空间计算设备` 在 `or` 下 73 条，多半只是含"设备"；`and`/`phrase` 收成 8 条。带无关词时 `or` 给 23 条（看起来"搜到了"），`and` 给 0——**要用"是否真的搜到"来判断，请显式传 `mode=and`**。`q` 为空时 `mode` 是空操作。
- **精确筛选**：`term/terms` 按 keyword 字段精确匹配，不参与排序。

**精确筛选参数的生效类型**（`type=all` 时尤其重要：类型专属参数**只作用于对应类型，其他类型照常返回**）

| 参数 | source | evidence | viewpoint | 说明 |
|---|:--:|:--:|:--:|---|
| `status` / `presentation_type` | ✅ | ✅ | ✅ | `identity.status` / `presentation.type` |
| `period` / `region` / `industry` / `source_type` | — | ✅ | — | evidence 专属；`period` 是**精确串**匹配，区间值会漏（`2023-2027` 匹配不到 `period=2024`） |
| `confidence_level` | ✅ | ✅ | — | viewpoint 经验层无此字段：对它传该参数**不报错也不筛**（返回全部 viewpoint） |
| `claim_type` / `applicable_scenario` / `cross_validation_mode` | — | — | ✅ | viewpoint 专属 |
| `responsible_role` | ✅ | ✅ | ✅ | nested `responsibility`，三类通用 |
| `source_ids` | ⛔ | ✅ | ✅ | **只查适用类型**：`type=all` 时 source 不参与；单类型 `type=source` 带它 → 返回 0 |
| `evidence_ids` | ⛔ | ⛔ | ✅ | 同上；`type=evidence` 带它 → 返回 0 |
| `project_id` / `project_ids` | ✅ | ✅ | ✅ | 见下面「项目范围」 |

> 实测锚点（project 1，24/349/24）：`type=all&region=火星` → 48（evidence 筛空，source 24 + viewpoint 24 照回）；`type=viewpoint&confidence_level=medium` → 24；`type=source&source_ids=[…]` → 0；`type=all&source_ids=["source:S001"]` → 179；`type=viewpoint&source_ids=[…]&evidence_ids=[…]` → 1（同一步内 AND）。
- **关联（引用溯源）**：`source_ids` / `evidence_ids` 用于"谁引用了它"。仅在**适用类型**上生效——`source_ids` 适用于 evidence、viewpoint；`evidence_ids` 仅适用 viewpoint。`type=all` 时只检索适用类型（不适用的类型直接不出结果，而非全量返回）；单类型请求若带了它不支持的关联参数则返回空结果。`source_ids`+`evidence_ids` 同时传，表示"**同一步**推理同时引用了该材料与该证据"。
- **职责（审计）筛选**：`responsible_role` 命中 `responsibility[].operator.role`，三类通用，不属于对象间关联。
- **`type=all`**：跨三类型合并的结果集，按相关度排序。
- **项目范围（重要变更）**：`project_id` / `project_ids` **都不传 = 全项目（全局检索）**；`project_id` 限定单项目；`project_ids` 取多项目并集（两者互斥，同传返回 400，空数组返回 400）。⚠️ 跨项目时 **`oirf_id` 会重号**（`source:S001` 每个项目都有）——**不要用它当列表 key 或详情键**，用 `id`（ObjectId，全局唯一）；点详情时把卡片里的 `project_id` 回传给 `/objects`。
- `highlight` 只有在 `q` 非空时才有内容；`inner_hits` 只在按 nested 字段（`responsible_role`/`source_ids`/`evidence_ids`）过滤时返回（标识命中的是哪一条 responsibility / 哪一步 reasoning.steps）。

### 3.3 示例

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"q":"空间计算","type":"evidence","project_id":1,"industry":"空间计算设备","status":"PENDING","size":3}'

# 收紧召回：所有词都要命中（默认 or 会给 73 条，and 给 8 条）
curl -s -X POST http://127.0.0.1:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"q":"空间计算设备","type":"all","mode":"and"}'
```

响应：

```jsonc
{
  "total": 15,
  "page": 1,
  "size": 3,
  "hits": [
    {
      "id": "6a9fbd1b270db0c081be679d",   // = ES _id = Mongo id（ObjectId 字符串）
      "object_type": "evidence",
      "project_id": 1,
      "oirf_id": "evidence:E028",
      "score": 28.29,                     // 相关度分
      "raw_score": 28.29,                 // 原始 BM25 分（调试用）
      "identity": { "name": "苹果引领空间计算时代", "object_type": "evidence", "status": "PENDING" },
      "presentation": { "subject": "苹果", "indicator": "行业引领判断", "value": "…", "period": "2024", "region": "全球" },
      "reasoning": { "source_ids": ["source:S005"] },
      "experience": { "confidence_level": "low", "original_publish": "澎湃新闻" },
      "responsibility": [ { "operation": "create", "operator": { "type": "ai", "role": "analyst" } } ],
      "highlight": { "identity.name": ["\u003cem\u003e空间\u003c/em\u003e\u003cem\u003e计算\u003c/em\u003e时代"] }
    }
  ]
}
```

### 3.4 `type=all` 响应要点

`score` 为**跨类型归一化**后的可比分数（0 到 1），`raw_score` 保留各索引原始分。适合跨 source/evidence/viewpoint 混合浏览。

### 3.5 关联检索示例

```bash
# 引用 source:S001 的对象（type=all 下只返回 evidence + viewpoint，source 不出现）
curl -s -X POST http://127.0.0.1:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"type":"all","project_id":1,"source_ids":["source:S001"]}'

# 引用 evidence:E005 的观点命题（仅 viewpoint）
curl -s -X POST http://127.0.0.1:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"type":"viewpoint","project_id":1,"evidence_ids":["evidence:E005"]}'
```

命中里 `inner_hits.reasoning.steps` 会标出引用它的那一步（含该步的推理文本 `to`）。

### 3.6 跨项目 / 全局检索

```bash
# 全局检索：不传项目参数 = 所有项目
curl -s -X POST http://127.0.0.1:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"q":"空间计算","type":"all"}'

# 多项目并集：项目 1 与 2 一起搜
curl -s -X POST http://127.0.0.1:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"q":"空间计算","type":"all","project_ids":[1,2]}'

# 单项目：只看项目 2
curl -s -X POST http://127.0.0.1:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"q":"空间计算","type":"all","project_id":2}'
```

三条的差别只在生成的过滤子句：全局**不加** `project_id` 子句、单项目加 `term`、多项目加 `terms`。响应里每条命中都带 `project_id`，**跨项目结果必须靠它 + `id` 定位对象**（`oirf_id` 跨项目会重号）。

---

## 4. 字段说明

**全文检索字段**（只有这些字段参与 `q` 的匹配）：

| type | 检索字段 |
|---|---|
| source | `identity.name`、`presentation.title`、`presentation.publisher` |
| evidence | `identity.name`、`presentation.subject`、`presentation.indicator`、`presentation.value` |
| viewpoint | `presentation.name`、`identity.name`、`experience.name` |

**精确筛选字段**：见 3.1 参数表，逐一映射到 keyword 字段。

**注意**：搜索响应只含"可搜/可筛"字段 + `identity`/`presentation`/`reasoning`/`experience`/`responsibility` 这些卡片字段 + `highlight`/`inner_hits`；**长文本**（`raw_texts`、`summary`、`content`、`explanation`、`narrative`、`*_reason`、`lifecycle` 等）不占体积，需要时用 `/objects` 取。

---

## 5. 完整对象 `GET /api/v1/objects/{object_type}/{oirf_id}?project_id=`

回 MongoDB 取**完整**对象（补全搜索卡片里没带的长文本、完整 reasoning/responsibility/lifecycle）。

| 参数 | 类型 | 说明 |
|---|---|---|
| `object_type` | path | `source` / `evidence` / `viewpoint` |
| `oirf_id` | path | 如 `source:S001` |
| `project_id` | query | 缺省 `1`，但**本端点靠 `oirf_id` 定位、只在一个项目内唯一**：从全局/多项目检索结果点进详情时，**必须传卡片里的 `project_id`**，否则会取到项目 1 的同号对象（串号） |

示例：

```bash
curl "http://127.0.0.1:8000/api/v1/objects/viewpoint/viewpoint:V001?project_id=1"
```

响应（完整对象字段原样返回，含长文本）：

```jsonc
{
  "id": "6a9fbd1b270db0c081be68ea",
  "oirf_id": "viewpoint:V001",
  "project_id": 1,
  "identity": { "name": "…", "object_type": "viewpoint", "status": "PENDING" },
  "presentation": { "name": "…", "content": "…长文本…", "explanation": "…" },
  "reasoning": { "steps": [ … ], "narrative": "…" },
  "experience": { "name": "…", "content": "…", "claim_type": "…", "cross_validation_mode": "…" },
  "responsibility": [ { "id": "responsibility:R0xx", "operation": "create", "operator": { "role": "analyst" }, "note": "…" } ],
  "lifecycle": []
}
```

---

## 6. 健康检查

```bash
curl http://127.0.0.1:8000/api/v1/health
# {"ok":true,"service":"oirf-search"}
```

---

## 7. 错误码

| 状态码 | 场景 | 响应 |
|---|---|---|
| `400` | `object_type` 非法（`/objects`） | `{"detail":"unknown object_type: '…' (expected one of ['source','evidence','viewpoint'])"}` |
| `404` | `/objects` 找不到对应对象 | `{"detail":"object not found"} ` |
| `422` | `/search` 参数校验失败（如 `type` 非法、`page<1`） | FastAPI 字段级错误 |
