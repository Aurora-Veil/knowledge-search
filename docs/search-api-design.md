# MongoDB + Elasticsearch 搜索接口方案（Python + FastAPI）

> 目标：把 Docker 里的 MongoDB（authority / OLTP 存储）与 Elasticsearch（全文检索引擎）接起来，
> 对外提供一套知识图谱搜索 API。搜索走 ES，完整对象/关联回 Mongo 补权威字段。

---

## ✅ 阶段状态（已落地 / 待做）

| 阶段 | 状态 | 说明 |
|---|---|---|
| 数据库存储 | ✅ 已落地、锁定 | 权威库 `knowledge_db`；3 集合 `project_id` 分区；`pptx_store` 已弃用 |
| id 模型 | ✅ 已落地 | `id = _id = ObjectId`（全局唯一），**无复合键**；`oirf_id` 仅项目内唯一（`source:S001`） |
| ES 索引 + mapping | ✅ 已落地 | 三索引 `knowledge_*`，`dynamic:false`，见 §4 |
| 全量同步 | ✅ 已落地 | `full_sync.py`：397 条，幂等重跑；见 §5 |
| 搜索 API | ⏳ 待实现 | 见 §6（设计已按最终 mapping 更新） |
| 增量同步 | ⏳ 待实现 | 写后 `sync_one` / Change Streams；见 §5.2 |

---

## 1. 总体架构

```
   ┌────────────┐   写入(权威)   ┌─────────────────┐   同步管道    ┌────────────────────┐
   │  Client/前端 │ ───────────►  │    写库          │ ───────────► │  Elasticsearch     │
   └────────────┘               │  Mongo knowledge_db│   full_sync │  knowledge_* 三索引  │
                                └────────┬────────┘             / sync_one  └─────────▲──────┘
                                         │                                                 │ 检索
                                         ▼                                                 ▼
                                 ┌──────────────────────────────────────────────────────────┐
                                 │  FastAPI 应用  /api/v1/search …                          │
                                 │  · /search        ：查 ES（全文+过滤+聚合+高亮）          │
                                 │  · /objects       ：按 (object_type, oirf_id, project)   │
                                 │                     回 Mongo 取完整权威字段               │
                                 │  · /associations  ：观点→证据→材料 图谱（ES terms + Mongo）│
                                 └──────────────────────────────────────────────────────────┘
```

- **MongoDB = 权威数据源**：唯一存储、对象间关系（`source_ids`/`evidence_ids`）、生命周期与状态。一切增删改写 Mongo。
- **Elasticsearch = 检索引擎**：全文检索、模糊、过滤聚合、高亮、相关性。**搜索只查 ES**。
- **接缝**：两个系统用**同一个 `_id`（ObjectId 字符串）**关联——搜索命中 ES 的某条，可凭同 ObjectId 回 Mongo 取完整对象。

---

## 2. 数据模型与 id 模型（已落地）

每个对象（source/evidence/viewpoint）共用一套字段：

```
{
  _id:     ObjectId,          # Mongo 主键，全局唯一
  id:      ObjectId,          # = _id（入库时回写），ES 文档 id 也用 str(_id)
  oirf_id: "source:S001",     # 项目内唯一引用键（source:S001 / evidence:E001 / viewpoint:V001）
  project_id: 1,
  identity:   { name, object_type, status },        # object_type ∈ source|evidence|viewpoint；status ∈ FORMAL|PENDING|DISPUTED|REJECTED
  presentation: { ... },      # 各类型字段不同（见下）
  reasoning:   { ... },       # 各类型不同
  experience:  { ... },       # 各类型不同
  lifecycle:   [ ],           # 生命周期（当前恒空数组）
  responsibility: [ { id, operation, operator{type,id,role}, changes, note, time } ],  # 责任链数组
}
```

**id 模型（关键）**：
- 全局唯一键 = **`_id`（ObjectId）**；`id` 字段在**入库时**由 `ingest.py` 生成：丢弃原始 JSON 的生成期 int `id` → 让 Mongo 自产 `_id` → 回写 `id = _id`。**无需复合键**。
- `oirf_id` 只在**单个项目内唯一**；跨项目同号（`source:S001` vs 另一项目的 `source:S001`）靠 `_id` 区分。
- 项目内软引用（`reasoning.source_ids`/`steps[].evidence_ids`）存**裸 `oirf_id`**，检索时**必须带 `project_id` 作用域**，否则跨项目同号会串。

---

## 3. ES 索引与映射（已落地）

**三个隔离索引**（每类一份干净 mapping，避免多态字段冲突）。三份 mapping 都在 `mapping/` 下，全为 `dynamic:false`（未映射字段不索引、但保留在 `_source` 供展示）、`number_of_shards:1`、`number_of_replicas:0`。

### 3.1 公共字段（三类通用）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | keyword | = ObjectId 字符串（全局唯一） |
| `project_id` | keyword | 项目作用域过滤键 |
| `oirf_id` | keyword | 项目内唯一引用 |
| `identity.name` | text (ik_max_word / ik_smart) | 对象名，可搜 |
| `identity.object_type` | keyword | source/evidence/viewpoint（由索引隐含） |
| `identity.status` | keyword | FORMAL/PENDING/DISPUTED/REJECTED |
| `responsibility` | **nested** | 责任链数组（见 §3.2） |

**`responsibility`（nested）**：数组、条目内聚，保留 `operation ↔ operator ↔ time` 同条目完整性。子字段：`id`(keyword)、`operation`(keyword)、`operator{type,id,role}`(keyword)、`time`(date)。`changes`/`note`/`operator.name` 未映射 → 仅 `_source` 展示、不索引。

### 3.2 source（`knowledge_source`）

| 字段 | 类型 | 可搜性 |
|---|---|---|
| `presentation.type` | keyword | 过滤 |
| `presentation.title` | text (ik) | 全文搜 |
| `presentation.uri` | keyword | 过滤 |
| `presentation.publisher` | keyword + `fields.text`(ik) | 过滤 / 全文搜 |
| `presentation.rights` | keyword | 过滤 |
| `experience.level` / `label` / `confidence_level` | keyword | 过滤 |

> 未映射（仅 `_source` 展示）：`presentation.summary/notes`、`experience.level_reason/confidence_reason`、`lifecycle`。

### 3.3 evidence（`knowledge_evidence`）

| 字段 | 类型 | 可搜性 |
|---|---|---|
| `presentation.subject` | keyword + `fields.text`(ik) | 过滤 / 全文搜 |
| `presentation.type` | keyword | 过滤 |
| `presentation.source_type` | keyword | 过滤 |
| `presentation.industry` | keyword | 过滤 |
| `presentation.indicator` | text (ik) | 全文搜 |
| `presentation.value` | text (ik) | 全文搜（核心） |
| `presentation.period` | text(standard) + `fields.keyword` | 精确过滤用 `.keyword` |
| `presentation.region` / `unit` | keyword | 过滤 |
| `reasoning.source_ids` | keyword | 关联（terms） |
| `experience.confidence_level` | keyword | 过滤 |
| `experience.original_publish` | keyword + `fields.text`(ik) | 过滤 / 全文搜 |

> 未映射（仅 `_source` 展示）：`presentation.raw_texts/notes`、`experience.confidence_reason`、`lifecycle`。

### 3.4 viewpoint（`knowledge_viewpoint`）

| 字段 | 类型 | 可搜性 |
|---|---|---|
| `presentation.name` | text (ik) | 全文搜 |
| `presentation.type` | keyword | 过滤 |
| `reasoning.steps` | **nested** | 见下 |
| `reasoning.steps.source_ids` / `evidence_ids` | keyword | 关联（nested terms） |
| `experience.name` | text (ik) | 全文搜 |
| `experience.applicable_scenario` / `claim_type` / `cross_validation_mode` | keyword | 过滤 |

> `reasoning.steps` 是嵌套数组（每步含 `source_ids/evidence_ids`），用 `nested` 保每步独立；`steps[].to`、`presentation.content/explanation`、`experience.content` 等未映射 → 仅 `_source` 展示。

---

## 4. 同步（已落地 full_sync；增量待做）

### 4.1 全量同步 `full_sync.py`（✅ 已完成）

```
读 Mongo(权威库) 三个集合 → 转 JSON 安全对象（ObjectId→str、datetime→iso）→ bulk 灌对应索引
ES 文档 _id = str(Mongo _id)（= ObjectId），全局唯一、幂等；重跑自 24/349/24 不递增。
```

- 已建索引：`knowledge_source` / `knowledge_evidence` / `knowledge_viewpoint`。
- 已验证：`_count` = 24 / 349 / 24，`distinct oirf_id` 与 Mongo 一致，中文检索（ik）可命中。
- 重跑：先 `es.indices.exists` 跳过已建索引；bulk 用确定性 `_id` upsert 覆盖。

### 4.2 增量同步（⏳ 待实现）

数据量小、低频写时用**写后回调**最简：

```python
def sync_one(project_id, oirf_id):
    """写库后调用：更新/删除单条 ES 文档。"""
    # 找到该 (project_id, oirf_id) 所在集合，es.index(_id=str(doc['_id']), document=...)
    # 删除时 es.delete(_id=...)
```

量大再换 **Change Streams**（pymongo `watch()` 长连接 → bulk 批量缓冲 + 重试）。

---

## 5. 搜索 API（设计已按最终 mapping 更新）

> 核心差异：**三索引**、**无 `text` 汇总字段**（撤回了），改为按类型 `multi_match`；`reasoning.steps` 与 `responsibility` 为 **`nested`**；`_id` 为 **ObjectId 字符串**。

### 5.0 本次锁定的接口约定（定稿）

| 约定 | 值 | 说明 |
|---|---|---|
| **端点形态** | **统一 `POST /api/v1/search`** + `type` 路由（含 `all`） | 不拆三个端点；`type` 决定路由到哪个索引 |
| **交付范围** | **先做 §5.1 search + §5.2 objects**；`/associations` 下一轮 | 先跑通"搜索 → 点进详情"主链路 |
| **`project_id` 默认** | **缺省 = 当前项目（`project_id=1`）**；跨项目显式传 | `oirf_id` 项目内唯一，默认当前项目防串号、更省调用 |

### 5.1 统一搜索 `POST /api/v1/search`

按 `type` 路由到对应索引；`type=all` 走 multi-index（每索引各自建查询再合并）。`project_id` **缺省取当前项目（1）**，显式传入则覆盖。

**请求体**

```jsonc
{
  "q": "空间计算",                    // 全文检索词；空=仅过滤
  "type": "evidence",                 // source | evidence | viewpoint | all
  "project_id": 1,                    // 可选；缺省=当前项目(1)，显式传则跨项目
  "status": "PENDING",
  "period": "2024",                   // 命中 presentation.period.keyword
  "region": "全球",
  "industry": "空间计算设备",
  "source_type": "secondary_public",
  "confidence_level": "medium",
  "responsible_role": "analyst",      // nested：responsibility.operator.role
  "evidence_ids": ["evidence:E001"],  // viewpoint 特有：nested reasoning.steps.evidence_ids
  "source_ids": ["source:S001"],      // terms / nested
  "page": 1,
  "size": 20,
  "highlight": true
}
```

**同类全文检索字段（`multi_match`，`type:best_fields`，`analyzer: ik_smart`），带字段权重（`field^boost`）**

> 权重含义：**只影响相关性排序，不影响召回**——某字段命中与否都会进结果，只是权重越高排越前。
> 已用真实数据实测校准（见 §6 末）。
> ⚠️ `presentation.subject` / `presentation.publisher` 是 **keyword + `.text` 子字段**：全文检索必须用 `subject.text` / `publisher.text`（裸字段只能精确匹配、不分词）。

- **source**（`identity.name` 已=出版方+标题，最完整干净；title 带域名垃圾后缀）
  ```
  identity.name^3
  presentation.title^2
  presentation.publisher.text^2
  ```
- **evidence**（`identity.name` 是主题摘要句，`value` 要么长描述要么纯数字——name 权重最高，短查询下能命中"真正讲这个"的文档，value 权重太低会把含该词的长描述跑题文档抬上来）
  ```
  identity.name^3
  presentation.subject.text^2
  presentation.indicator^2
  presentation.value^2
  ```
- **viewpoint**（`presentation.name` 与 `identity.name` 在数据中一字不差（重复内容）；`experience.name` 是判断/角度标签：态势判断/归因/格局/成本结构）
  ```
  presentation.name^3
  identity.name^2.5     # 与 presentation.name 重复，保留以防个别文档不一致
  experience.name^2     # 角度/标签词要能上位（如搜"竞争格局"）
  ```
- **`type=all`**：对三个索引分别按各自的 multi_match 后合并，按 score 排序（权重尺度一致，可合并排名）。

### 5.1.1 精确筛选（filter）实现

**核心机制**：精确匹配用 `term`（单值）/`terms`（多值），**打在 keyword 字段**上（`term` 对 text 字段基本失效）。全部子句进 `bool.filter`——**不参与打分**（不干扰相关度排序）、**ES 自动缓存**（多条件下重复查更快）。

**可用精确筛选字段（按类型，自 mapping）**

| 类型 | keyword 精确字段 |
|---|---|
| source | `identity.status`、`presentation.type/uri/rights/publisher`、`experience.level/label/confidence_level` |
| evidence | `identity.status`、`presentation.type/source_type/industry/region/unit/subject`、`presentation.period.keyword`、`reasoning.source_ids`、`experience.confidence_level` |
| viewpoint | `identity.status`、`presentation.type`、`experience.applicable_scenario/claim_type/cross_validation_mode`、`reasoning.steps.source_ids/evidence_ids`(nested) |
| 共性 | `project_id`、`identity.object_type`（索引已隐含） |

> ⚠️ `subject`/`publisher` 过滤用**裸 keyword 字段**（全文检索才用 `.text`）。`period` 过滤必须用 **`presentation.period.keyword`**（原字段是 text+standard，不能直接 term）。

**入参 → filter 子句（类型感知）**。关键歧义：`source_ids` 在 evidence 里是**扁平 keyword**（`reasoning.source_ids`）、在 viewpoint 里是**嵌套**（`reasoning.steps.source_ids`）——同一入参按 `type` 映射成不同查询。

```python
def build_filters(type_, p):
    f = []
    if p.get('project_id') is not None: f.append(term('project_id', p['project_id']))
    if p.get('status'):                 f.append(term('identity.status', p['status']))
    if type_ in ('evidence', 'all'):                        # evidence 专属
        if p.get('period'):      f.append(term('presentation.period.keyword', p['period']))
        if p.get('region'):      f.append(term('presentation.region', p['region']))
        if p.get('industry'):    f.append(term('presentation.industry', p['industry']))
        if p.get('source_type'): f.append(terms('presentation.source_type', p['source_type']))
    if type_ in ('viewpoint', 'all'):                       # viewpoint 专属
        if p.get('claim_type'):  f.append(term('experience.claim_type', p['claim_type']))
    # —— 关联（类型感知）——
    if p.get('source_ids'):
        if type_ == 'evidence':    f.append(terms('reasoning.source_ids', p['source_ids']))                     # 扁平
        elif type_ == 'viewpoint': f.append(nested('reasoning.steps', terms('reasoning.steps.source_ids', p['source_ids'])))  # 嵌套
    if p.get('evidence_ids') and type_ == 'viewpoint':
        f.append(nested('reasoning.steps', terms('reasoning.steps.evidence_ids', p['evidence_ids'])))
    if p.get('responsible_role'):
        f.append(nested('responsibility', term('responsibility.operator.role', p['responsible_role'])))
    return f
```

**`type=all` 的正确处理**：不能用单个多索引查询再带 `industry` 这类 evidence 专属条件——source/viewpoint 索引没这字段，`term` 匹配 0，整批被过滤、丢掉其他类型（错误）。正解：对三个索引**各自建查询、结果按 score 合并**，每个索引只加其字段表里有的子句。

```python
def search(p):
    if p['type'] == 'all':
        hits = []
        for t in ('source', 'evidence', 'viewpoint'):         # 只加该索引存在的子句
            hits += es.search(index='knowledge_%s' % t, **build_query(t, p))['hits']['hits']
        return merge_by_score(hits)
    return es.search(index='knowledge_%s' % p['type'], **build_query(p['type'], p))
```

**示例**：入参 `{type:"all", q:"空间计算", project_id:1, industry:"空间计算设备", status:"PENDING"}` → evidence 索引：
```jsonc
{ "query": { "bool": { "must": [
    { "multi_match": { "query": "空间计算", "analyzer": "ik_smart", "type": "best_fields",
        "fields": ["identity.name^3", "presentation.subject.text^2", "presentation.indicator^2", "presentation.value^2"] } }
  ], "filter": [
    { "term": { "project_id": 1 } },
    { "term": { "identity.status": "PENDING" } },
    { "term": { "presentation.industry": "空间计算设备" } } ] } } }
```
source/viewpoint 索引**不带** `industry` 子句。

**两个必知坑**：① `period` 有区间值（如 `2023-2027`），`period=2024` 的 term 精确匹配会漏区间——后续加归一化年份字段，当前按精确串匹配并标注。② `terms` 传参：`source_type`/`source_ids`/`evidence_ids` 支持列表（多值），单值亦可。

**查询构造其他要点**
- `must`：`q` 存在时 `multi_match`（字段用加权字段、`type:best_fields`、`analyzer: ik_smart`）。
- `nested`：凡涉及 `responsibility.*` 或（viewpoint）`reasoning.steps.*` → 用 `nested` 查询包住。
- **`inner_hits`（保留 nested 的原因）**：用户期望"看到命中的那一条"（`responsibility` 哪条 / `reasoning.steps` 哪步）。当请求按 nested 子字段过滤（`responsible_role`→`responsibility`、`source_ids`/`evidence_ids`→`reasoning.steps`）时，nested 查询加 `"inner_hits": {"_source": true}`，响应命中里带 `inner_hits.<path>` 返回命中的那个数组元素（含 `_source`，如步骤的 `to`/`operator`）。**这一步只有 `nested` 能做**，平铺 `object` 无法返回命中元素，故这两处**保留 nested**。
- 高亮：`pre_tags/post_tags = <em>...</em>`，字段取所属索引 multi_match 的字段。
- **聚合/过滤字段（keyword 子字段）**：`presentation.period.keyword`、`presentation.region`、`presentation.industry`、`presentation.source_type`、`experience.confidence_level`、`identity.status` 等——可对 `filter` 精确筛选，也预留给独立聚合端点；**搜索响应不带 facets**（定稿：纯粹结果）。

**响应体（定稿：轻卡片 + score，不带 facets）**

> 每条命中（hit）= **识别键 + 各类可索引（可搜/可筛）字段 + highlight**；**不含未映射长文本**（`presentation.raw_texts/notes/summary/content/explanation`、`experience.*_reason`、`lifecycle`、`responsibility.changes/note/operator.name`）——那些走 `/objects` 回 Mongo 取。规则：**要搜索/要筛选的字段一定带回来；纯展示长文本不占体积。**

```jsonc
{
  "total": 15,
  "page": 1, "size": 20, "took_ms": 8,
  "hits": [
    {
      // 识别键（置顶，方便客户端跳详情/关联）
      "id": "6a9fbd1b270db0c081be6782",    // = _id (ObjectId 字符串) = Mongo id
      "object_type": "evidence",
      "project_id": 1,
      "oirf_id": "evidence:E001",
      "score": 28.3,                        // 相关度（保留，可显示/按相关度排序/调试）
      // 各类卡片字段（= 索引里能搜/能筛的字段）
      "identity": { "name": "空间计算设备包含AR、VR、MR终端", "object_type": "evidence", "status": "PENDING" },
      "presentation": { "subject": "空间计算设备", "indicator": "设备构成", "value": "AR、VR、MR等终端设备",
                        "period": "2024", "region": "全球" },
      "reasoning": { "source_ids": ["source:S001"] },
      "experience": { "confidence_level": "medium", "original_publish": "..." },
      "responsibility": [ { "operation": "create", "operator": { "type": "person", "role": "analyst" }, "time": "..." } ],
      // 命中高亮（把命中的词标出来，前端渲染摘要时用）
      "highlight": {
        "identity.name": ["<em>空间计算</em>设备包含AR、VR、MR终端"],
        "presentation.value": ["AR、VR、MR等<em>终端设备</em>"]
      }
    }
  ]
}
```

> `highlight` 默认开（搜索的"看点"就在这）；`score` 保留做调试/排序。

**命中条目 `inner_hits`（按 nested 子字段过滤时附带）**：响应命中里增加 `inner_hits.<path>`，标识是哪一条 `responsibility` / 哪一步 `reasoning.steps` 命中了过滤条件。实测（viewpoint V001，`evidence_ids` 过滤）：

```jsonc
"inner_hits": {
  "reasoning.steps": { "hits": { "hits": [
    { "_source": { "source_ids": ["source:S002","source:S001"],
                   "evidence_ids": ["evidence:E005","evidence:E006","evidence:E029","evidence:E030"],
                   "to": "全球与中国2023年前三季度VR/AR出货量分别为449万台、41万台与31.5万台、12.5万台" } }
  ] } }
}
```
> 这对**关联追踪**（"这条证据被哪一步引用、那一步的推理文本是什么"）特别有用；`to` 等未映射字段在 `_source` 里仍可见（`dynamic:false` 保留）。

### 5.2 完整对象 `GET /api/v1/objects/{object_type}/{oirf_id}?project_id=`

回 Mongo 取**完整权威字段**（原样 `_source` 不完整处，如完整 `reasoning`、`responsibility`、`identity` 及未映射长文本）。**必须带 `project_id`**（同号对象跨项目会串号）。

### 5.3 关联图谱 `GET /api/v1/associations/{object_type}/{oirf_id}?project_id=`

以 `oirf_id` 为起点，ES `terms`/`nested` 查关联 + Mongo join：
- **viewpoint V001** → `reasoning.steps.evidence_ids`（nested）→ 其证据 → `reasoning.source_ids` → 材料。
- 全程**限定 `project_id`**，否则 `evidence:S005` 会串到别的项目。

---

## 6. 中文分词与检索细节

- **索引侧** `ik_max_word`（最大切分，召回高）；**查询侧** `ik_smart`（粒度粗，精确）。
- 精确短语：`match_phrase`；宽松：`match` + `fuzziness: "AUTO"`。
- 过滤/聚合一律用 `keyword` 子字段（`term`/`terms`/`aggs`），不参与分析。

> **权重校准（真实数据实测）**：`identity.name` 是精炼主题摘要句，短关键词下最能命中"真正讲这个"的文档；
> `value` 常是长描述或纯数字，权重若高于 name，会把"仅在长描述里碰巧含该词"的跑题文档抬上来（如搜「空间计算」时
> 《三款头显均采用Pancake光学方案》排前）。故 evidence 采用 name 最高。`viewpoint` 的 `presentation.name` 与
> `identity.name` 数据中一字不差（重复内容），加权即重复；`experience.name` 是判断/角度标签（态势判断/归因/格局/
> 成本结构），搜角度词（如「竞争格局」）时须能上位，故给 `^2`。`source` 的 `identity.name` 已是「出版方+标题」，
> 最完整干净，作最高权重。

---

## 7. 环境与现状

| 组件 | 容器 / 镜像 | 端口 | 状态 |
|---|---|---|---|
| MongoDB | `mongodb` (mongodb-community-server:latest) | 27017 | Up，`knowledge_db` 3 集合 |
| Elasticsearch | `es01` (elasticsearch:9.5.3，含 analysis-ik) | 9200 | Up，`knowledge_*` 三索引 |
| Kibana | `kibana` (kibana:9.5.3) | 5601 | Up；**Search 主页需 ES 安全**（见 §8） |

**已确认数据**：project 1，`sources(24)/evidence(349)/viewpoints(24)`；`id = _id = ObjectId`；ES `_count` 一致。

---

## 8. 待实现 / 风险

| 项 | 说明 |
|---|---|
| **搜索 API（本轮）** | `POST /api/v1/search`（§5.1）+ `GET /api/v1/objects`（§5.2），FastAPI `app/` 包；`/associations`（§5.3）下一轮 |
| **增量同步** | 写后 `sync_one`（§4.2）；量大再 Change Streams |
| **`period` 区间过滤** | `period` 有区间值（如 `2023-2027`），精确筛 `period=2024` 会漏掉区间；后续可加归一化年份字段 |
| **内容去重** | 内容重叠少，暂缓；量级上来再考虑 content-key 去重 |
| **深分页** | 量大改用 `search_after`（当前 `from/size` 够用） |