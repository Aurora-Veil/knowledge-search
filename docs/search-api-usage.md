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
| `project_id` | int | `1` | 缺省=当前项目；显式传则查另一项目 |
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
- **精确筛选**：`term/terms` 按 keyword 字段精确匹配，不参与排序。
- **关联（引用溯源）**：`source_ids` / `evidence_ids` 用于"谁引用了它"。仅在**适用类型**上生效——`source_ids` 适用于 evidence、viewpoint；`evidence_ids` 仅适用 viewpoint。`type=all` 时只检索适用类型（不适用的类型直接不出结果，而非全量返回）；单类型请求若带了它不支持的关联参数则返回空结果。`source_ids`+`evidence_ids` 同时传，表示"**同一步**推理同时引用了该材料与该证据"。
- **职责（审计）筛选**：`responsible_role` 命中 `responsibility[].operator.role`，三类通用，不属于对象间关联。
- **`type=all`**：跨三类型合并的结果集，按相关度排序。
- `highlight` 只有在 `q` 非空时才有内容；`inner_hits` 只在按 nested 字段（`responsible_role`/`source_ids`/`evidence_ids`）过滤时返回（标识命中的是哪一条 responsibility / 哪一步 reasoning.steps）。

### 3.3 示例

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"q":"空间计算","type":"evidence","project_id":1,"industry":"空间计算设备","status":"PENDING","size":3}'
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
| `project_id` | query | 可选，缺省 `1`；**必须限定项目**，否则同号 oirf_id 会串到其他项目 |

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
