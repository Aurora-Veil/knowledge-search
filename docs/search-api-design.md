# MongoDB + Elasticsearch 搜索接口方案（Python + FastAPI）

> 目标：把 Docker 里的 MongoDB（authority / OLTP 存储）与 Elasticsearch（全文检索引擎）接起来，
> 对外提供一套知识图谱搜索 API。搜索走 ES，完整对象/关联回 Mongo 补权威字段。

---

## ✅ 阶段状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| 数据库存储 | ✅ 已落地、锁定 | 权威库 `knowledge_db`；3 集合 `project_id` 分区 |
| id 模型 | ✅ 已落地 | `id = _id = ObjectId`（全局唯一），**无复合键**；`oirf_id` 仅项目内唯一（`source:S001`） |
| ES 索引 + mapping | ✅ 已落地 | 三索引 `knowledge_*`，`dynamic:false`，见 §3 |
| 同步层 | 📦 已移出项目 | 代码归档于 `..\9.8-sync-archive\app-sync\`，本文件的旧同步章节也已随快照归档（`..\9.8-sync-archive\search-api-design.md.snapshot`）。库与 ES 已建好并冻结（24/349/24、零漂移），**检索不依赖它** |
| 搜索 API | ✅ 已实现并回归 | `POST /api/v1/search`（§4.1）+ `GET /api/v1/objects`（§4.2） |
| 关联图谱 API | 📝 设计定稿、**未实现** | `GET /api/v1/associations`（§4.3）：接口形状、查询计划、实测边界与验收锚点已定稿，代码 0 行 |

---

## 1. 总体架构

```
   ┌────────────┐   写入(权威)   ┌─────────────────┐   同步（已归档）  ┌────────────────────┐
   │  Client/前端 │ ───────────►  │    写库          │ ─ ─ ─ ─ ─ ─ ─►  │  Elasticsearch     │
   └────────────┘               │  Mongo knowledge_db│   full_sync    │  knowledge_* 三索引  │
                                └────────┬────────┘   (已移出项目)     └─────────▲──────┘
                                         │                                                 │ 检索
                                         ▼                                                 ▼
                                 ┌──────────────────────────────────────────────────────────┐
                                 │  FastAPI 应用  /api/v1/search …                          │
                                 │  · /search        ：查 ES（全文 + 精确筛选 + 高亮）        │
                                 │  · /objects       ：按 (object_type, oirf_id, project)   │
                                 │                     回 Mongo 取完整权威字段               │
                                 │  · /associations  ：观点→证据→材料 图谱（ES 单源，见 §4.3）│
                                 └──────────────────────────────────────────────────────────┘
```

- **MongoDB = 权威数据源**：唯一存储、对象间关系（`source_ids`/`evidence_ids`）、生命周期与状态。一切增删改写 Mongo。
- **Elasticsearch = 检索引擎**：全文检索、过滤聚合、高亮、相关性。**搜索只查 ES**。
- **接缝**：两个系统用**同一个 `_id`（ObjectId 字符串）**关联——搜索命中 ES 的某条，可凭同 ObjectId 回 Mongo 取完整对象。
- **同步管道已移出项目**（见阶段状态表）：数据已冻结，检索不需要写库动作；将来要恢复同步，见归档目录。

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

- 全局唯一键 = **`_id`（ObjectId）**；`id` 字段在**导入时**生成：丢弃原始 JSON 的生成期 int `id` → 让 Mongo 自产 `_id` → 回写 `id = _id`。**无需复合键**。
- `oirf_id` 只在**单个项目内唯一**；跨项目同号（`source:S001` vs 另一项目的 `source:S001`）靠 `_id` 区分。
- 项目内软引用（`reasoning.source_ids`/`steps[].evidence_ids`）存**裸 `oirf_id`**；`oirf_id` **跨项目会重号**，而**检索缺省是全项目**（见 §4.0），所以跨项目结果里**不要用 `oirf_id` 定位对象**——用 `id`（ObjectId，全局唯一），取详情时回传卡片里的 `project_id`。

---

## 3. ES 索引与映射（已落地）

**三个隔离索引**（每类一份干净 mapping，避免多态字段冲突）。三份 mapping 都在 `mapping/` 下，全为 `dynamic:false`（未映射字段不索引、但保留在 `_source` 供展示）、`number_of_shards:1`、`number_of_replicas:0`。

**字段可搜性的三类**（决定了它能做全文检索还是精确筛选）：

| 映射类型 | 能力 | 用途 | 查询写法 |
|---|---|---|---|
| `text`（ik） | 分词匹配、参与打分 | 全文检索 | `multi_match` |
| `keyword` | 整串相等、不打分 | 精确筛选 | `term` / `terms` |
| `nested` | 数组条目内聚 | 精确筛选（数组元素） | `nested` 包住 `term`/`terms` |

> ⚠️ **`keyword` + `.text` 子字段**（source 的 `publisher`、evidence 的 `subject`/`original_publish`）是反过来的写法：**父字段是 keyword（精确筛选用它）**，`.text` 才是分词副本（全文检索用）。全文检索必须写 `…text`；筛选用裸父字段。

### 3.1 公共字段（三类通用）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | keyword | = ObjectId 字符串（全局唯一） |
| `project_id` | keyword | 项目作用域过滤键 |
| `oirf_id` | keyword | 项目内唯一引用 |
| `identity.name` | text (ik_max_word / ik_smart) | 对象名，可搜 |
| `identity.object_type` | keyword | source/evidence/viewpoint（由索引隐含） |
| `identity.status` | keyword | FORMAL/PENDING/DISPUTED/REJECTED |
| `responsibility` | **nested** | 责任链数组（见下） |

**`responsibility`（nested）**：数组、条目内聚，保留 `operation ↔ operator ↔ time` 同条目完整性。子字段：`id`(keyword)、`operation`(keyword)、`operator{type,id,role}`(keyword)、`time`(date)。`changes`/`note`/`operator.name` 未映射 → 仅 `_source` 展示、不索引。

### 3.2 source（`knowledge_source`）

| 字段 | 类型 | 用途 |
|---|---|---|
| `presentation.type` | keyword | 精确筛选 |
| `presentation.title` | text (ik) | 全文检索 |
| `presentation.uri` | keyword | 精确筛选 |
| `presentation.publisher` | **keyword** + `fields.text`(ik) | **裸字段精确筛选（API 参数 `publisher`）/ `.text` 全文检索** |
| `presentation.rights` | keyword | 精确筛选 |
| `experience.level` / `label` / `confidence_level` | keyword | 精确筛选 |

> 未映射（仅 `_source` 展示）：`presentation.summary/notes`、`experience.level_reason/confidence_reason`、`lifecycle`。

### 3.3 evidence（`knowledge_evidence`）

| 字段 | 类型 | 用途 |
|---|---|---|
| `presentation.subject` | **keyword** + `fields.text`(ik) | 裸字段精确筛选 / `.text` 全文检索 |
| `presentation.type` | keyword | 精确筛选 |
| `presentation.source_type` | keyword | 精确筛选 |
| `presentation.industry` | keyword | 精确筛选 |
| `presentation.indicator` | text (ik) | 全文检索 |
| `presentation.value` | text (ik) | 全文检索（核心） |
| `presentation.period` | text(standard) + `fields.keyword` | 精确筛选用 `.keyword` |
| `presentation.region` / `unit` | keyword | 精确筛选 |
| `reasoning.source_ids` | keyword | 关联（terms） |
| `experience.confidence_level` | keyword | 精确筛选 |
| `experience.original_publish` | **keyword** + `fields.text`(ik) | **裸字段精确筛选（API 参数 `publisher`）/ `.text` 全文检索** |

> 未映射（仅 `_source` 展示）：`presentation.raw_texts/notes`、`experience.confidence_reason`、`lifecycle`。

### 3.4 viewpoint（`knowledge_viewpoint`）

| 字段 | 类型 | 用途 |
|---|---|---|
| `presentation.name` | text (ik) | 全文检索 |
| `presentation.type` | keyword | 精确筛选 |
| `reasoning.steps` | **nested** | 见下 |
| `reasoning.steps.source_ids` / `evidence_ids` | keyword | 关联（nested terms） |
| `experience.name` | text (ik) | 全文检索 |
| `experience.applicable_scenario` / `claim_type` / `cross_validation_mode` | keyword | 精确筛选 |

> `reasoning.steps` 是嵌套数组（每步含 `source_ids/evidence_ids`），用 `nested` 保每步独立；`steps[].to`、`presentation.content/explanation`、`experience.content` 等未映射 → 仅 `_source` 展示。
> **viewpoint 没有"来源/出版方"字段**——这是 `publisher` 对 viewpoint 采用严格语义（直接不出结果）的原因。

---

## 4. 搜索 API

> 核心形态：**三索引**、**无 `text` 汇总字段**（已撤回），按类型 `multi_match`；`reasoning.steps` 与 `responsibility` 为 **`nested`**；`_id` 为 **ObjectId 字符串**。

### 4.0 本次锁定的接口约定（定稿）

| 约定 | 值 | 说明 |
|---|---|---|
| **端点形态** | **统一 `POST /api/v1/search`** + `type` 路由（含 `all`） | 不拆三个端点；`type` 决定路由到哪个索引 |
| **交付范围** | **§4.1 search + §4.2 objects 已交付**；**§4.3 associations 已定稿、未实现** | 先跑通"搜索 → 点进详情"主链路；图谱端点设计见 §4.3 |
| **项目范围** | **缺省 = 全项目（全局检索）**；`project_id` 传单值 = 单项目、传数组 = 多项目并集；**传 `[]` 等同不传** | 多项目是常态需求，默认全局更符合"先搜到、再定位"；跨项目时 `oirf_id` 重号 ⇒ **定位一律用 `id`（ObjectId）**，详情回传 `project_id` |
| **筛选两族** | **集合限定族**（`source_ids`/`evidence_ids`/`publisher`）：类型不适用则**直接不查**；**字段取值族**（`period`/`region`/`confidence_level` 等）：类型无此字段则**忽略该条件、照常返回** | 详见 §4.1.2 |

### 4.1 统一搜索 `POST /api/v1/search`

按 `type` 路由到对应索引；`type=all` 时对三个索引**各自建查询再按归一化分合并**。项目范围缺省不设限（= 全项目）：`project_id` 传单值 → `terms` 单元素、传数组 → `terms` 多值、不传或传 `[]` → **不加子句**（`project_id` 是 keyword，取值统一字符串化）。

**请求体**

```jsonc
{
  "q": "空间计算",                    // 全文检索词；空=仅筛选
  "type": "evidence",                 // source | evidence | viewpoint | all
  "mode": "or",                       // or(默认) | and | phrase —— 全文匹配松紧；只改召回不改权重口径；q 为空时无意义
  "project_id": 1,                    // 可选：单值=单项目 / 数组=多项目并集 / 不传或 [] = 全项目
  "status": "PENDING",
  "presentation_type": "历史值",
  "period": "2024",                   // 命中 presentation.period.keyword
  "region": "全球",
  "industry": "空间计算设备",
  "source_type": "secondary_public",
  "publisher": "澎湃新闻",             // 来源：source→presentation.publisher / evidence→experience.original_publish（keyword 整串）
  "confidence_level": "medium",
  "claim_type": "态势判断",
  "applicable_scenario": "…",
  "cross_validation_mode": "…",
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
> 已用真实数据实测校准（见 §5 末）。
> ⚠️ `presentation.subject` / `presentation.publisher` / `experience.original_publish` 是 **keyword + `.text` 子字段**：全文检索必须用 `.text`（裸字段只能精确匹配、不分词）。

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
  experience.original_publish.text^2   # 来源名，^2 与 subject 同级
  ```
  > **`original_publish.text` 是"模糊找来源"的入口**：它让 `q=澎湃` 能命中那 1 条来自澎湃新闻的材料（加之前为 0）。但它**只是模糊**——`q=澎湃新闻` 会被 ik 切成「澎湃」+「新闻」而 OR 匹配出 **15 条**（9 条腾讯新闻被带入）。要"只看某来源"必须用 `publisher` 参数（§4.1.2）。
- **viewpoint**（`presentation.name` 与 `identity.name` 在数据中一字不差（重复内容）；`experience.name` 是判断/角度标签：态势判断/归因/格局/成本结构）
  ```
  presentation.name^3
  identity.name^2.5     # 与 presentation.name 重复，保留以防个别文档不一致
  experience.name^2     # 角度/标签词要能上位（如搜"竞争格局"）
  ```
- **`type=all`**：对三个索引分别按各自的 multi_match 后合并，**按 max-score 归一化分**（`score/max_score` → 0~1）排序——**不能直接比原始 BM25 `_score`**：不同索引规模 `N` 使 idf 标尺不同（evidence 349 条 vs source/viewpoint 24 条，idf 差 ~2 倍；`_explain` 实测 evidence identity.name idf≈4.15 vs source≈1.97，而 boost 同为 ^3、tf 同为 1），字段/权重拓扑亦异。归一化后各类型同标尺、可比排名；原始分另存 `raw_score` 供调试。调 BM25 `k1/b` 治不了（只管 tf 饱和/长度归一，不碰 idf）。

#### 4.1.1 精确筛选（filter）实现

**核心机制**：精确匹配用 `term`（单值）/`terms`（多值），**打在 keyword 字段**上（`term` 对 text 字段基本失效）。全部子句进 `bool.filter`——**不参与打分**（不干扰相关度排序）、**ES 自动缓存**（多条件下重复查更快）。

> ⚠️ **数组参数必须用 `terms`**：`term` 会对入参做 `str()`，把 `["知乎","知乎专栏"]` 变成字符串 `"['知乎', '知乎专栏']"` 去精确匹配 → **静默 0 条**。`_terms()` 同时接受标量与数组，是唯一正确入口。

**入参 → filter 子句（类型感知）**。关键歧义：`source_ids` 在 evidence 里是**扁平 keyword**（`reasoning.source_ids`）、在 viewpoint 里是**嵌套**（`reasoning.steps.source_ids`）；`publisher` 在两个类型里映射到**不同字段名**（`presentation.publisher` vs `experience.original_publish`）——同一入参按 `type` 映射成不同查询。

```python
def build_filters(type_, p):
    f = []
    pid = p.get('project_id')
    if pid not in (None, []):                                   # 不传 / [] = 全项目
        f.append(terms('project_id', pid))                      # 单值 → terms 单元素，多值 → 并集
    if p.get('status'):            f.append(term('identity.status', p['status']))
    if p.get('presentation_type'): f.append(term('presentation.type', p['presentation_type']))
    if p.get('publisher') and type_ in PUBLISHER_FIELD:          # 来源：两类型字段名不同
        f.append(terms(PUBLISHER_FIELD[type_], p['publisher']))
    if type_ == 'evidence':                                      # evidence 专属（无此字段的类型忽略这些参数）
        if p.get('period'):      f.append(term('presentation.period.keyword', p['period']))
        if p.get('region'):      f.append(term('presentation.region', p['region']))
        if p.get('industry'):    f.append(term('presentation.industry', p['industry']))
        if p.get('source_type'): f.append(terms('presentation.source_type', p['source_type']))
    if p.get('confidence_level') and type_ in ('source', 'evidence'):
        f.append(term('experience.confidence_level', p['confidence_level']))
    if type_ == 'viewpoint':                                     # viewpoint 专属
        if p.get('claim_type'):             f.append(term('experience.claim_type', p['claim_type']))
        if p.get('applicable_scenario'):    f.append(term('experience.applicable_scenario', p['applicable_scenario']))
        if p.get('cross_validation_mode'):  f.append(term('experience.cross_validation_mode', p['cross_validation_mode']))
    # —— 关联（类型感知）——
    if p.get('source_ids') and type_ == 'evidence':               # 扁平
        f.append(terms('reasoning.source_ids', p['source_ids']))
    if type_ == 'viewpoint':                                      # 嵌套：同一步内 AND
        steps = []
        if p.get('source_ids'):   steps.append(terms('reasoning.steps.source_ids', p['source_ids']))
        if p.get('evidence_ids'): steps.append(terms('reasoning.steps.evidence_ids', p['evidence_ids']))
        if steps: f.append(nested('reasoning.steps', {'bool': {'filter': steps}}))
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

#### 4.1.2 两族筛选语义（重要）

"类型不适用"有两种正确处理，取决于参数限定的是什么：

| 族 | 参数 | 不适用的类型 | 实现 |
|---|---|---|---|
| **集合限定族** | `source_ids`、`evidence_ids`、`publisher` | **直接不查该类型**（结果里不出现） | `_applicable_types()` 与类型表取交集 |
| **字段取值族** | `period`、`region`、`industry`、`source_type`、`confidence_level`、`claim_type`、`applicable_scenario`、`cross_validation_mode` | **忽略该条件、照常返回** | 只在对应 `type_` 分支里加子句 |

理由：前者限定的是"**哪些对象算数**"（没有该属性的对象拿不出结果，返回它等于没筛）；后者限定的是"**某类型的字段取值**"（对没有该字段的类型没有约束力）。

```python
ASSOC_SOURCE_IDS_TYPES   = ('evidence', 'viewpoint')
ASSOC_EVIDENCE_IDS_TYPES = ('viewpoint',)
PUBLISHER_FIELD          = {'source': 'presentation.publisher',
                            'evidence': 'experience.original_publish'}

def _applicable_types(p, base=('source', 'evidence', 'viewpoint')):
    types = set(base)
    if p.get('source_ids'):   types &= set(ASSOC_SOURCE_IDS_TYPES)
    if p.get('evidence_ids'): types &= set(ASSOC_EVIDENCE_IDS_TYPES)
    if p.get('publisher'):    types &= set(PUBLISHER_FIELD)
    return types
```

- `publisher` 归**集合限定族**：viewpoint 没有来源字段 → `type=all&publisher=…` 时 viewpoint 直接出局。
- 单类型显式请求若带不适用参数 → 返回 **0 条**（如 `type=source&source_ids=[…]`、`type=viewpoint&publisher=…`）。
- 实测（project 1，24/349/24）：`type=viewpoint&publisher=澎湃新闻` → 0；`type=all&region=火星` → 48（evidence 筛空，source 24 + viewpoint 24 照回）；`type=all&source_ids=['source:S001']` → 179；`type=viewpoint&source_ids=[…]&evidence_ids=[…]` → 1（同一步内 AND）。

**`publisher` 实测锚点**

| 请求 | 结果 | 说明 |
|---|---|---|
| `publisher=澎湃新闻` | **2** | source 1 + evidence 1 |
| `q=空间计算` + `publisher=澎湃新闻` | **2** | 内容 AND 来源（`multi_match` 做不到，必须靠 filter） |
| `publisher=Wind` | **35** | source 1 + evidence 34 |
| `publisher=知乎` / `publisher=知乎专栏` | **5** / **19** | 两索引用词不同 |
| `publisher=["知乎","知乎专栏"]` | **24** | 多选并集（`terms`） |
| `publisher=澎湃`（不完整值） | **0** | keyword 整串匹配，值必须完整 |
| `publisher=[]` | **397** | 等同不传（不设限） |

#### 4.1.3 响应体（定稿：轻卡片 + score，不带 facets）

> 每条命中（hit）= **识别键 + 各类可索引（可搜/可筛）字段 + highlight**；**不含未映射长文本**（`presentation.raw_texts/notes/summary/content/explanation`、`experience.*_reason`、`lifecycle`、`responsibility.changes/note/operator.name`）——那些走 `/objects` 回 Mongo 取。规则：**要搜索/要筛选的字段一定带回来；纯展示长文本不占体积。**

```jsonc
{
  "total": 15,
  "page": 1, "size": 20,
  "hits": [
    {
      // 识别键（置顶，方便客户端跳详情/关联）
      "id": "6a9fbd1b270db0c081be6782",    // = _id (ObjectId 字符串) = Mongo id
      "object_type": "evidence",
      "project_id": 1,
      "oirf_id": "evidence:E001",
      "score": 28.3,                        // 相关度（type=all 时为跨类型归一化分 0~1）
      "raw_score": 28.3,                    // 该索引原始 BM25 分（调试用）
      // 各类卡片字段（= 索引里能搜/能筛的字段）
      "identity": { "name": "空间计算设备包含AR、VR、MR终端", "object_type": "evidence", "status": "PENDING" },
      "presentation": { "subject": "空间计算设备", "indicator": "设备构成", "value": "AR、VR、MR等终端设备",
                        "period": "2024", "region": "全球" },
      "reasoning": { "source_ids": ["source:S001"] },
      "experience": { "confidence_level": "medium", "original_publish": "…" },
      "responsibility": [ { "operation": "create", "operator": { "type": "person", "role": "analyst" }, "time": "…" } ],
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
> 纯筛选请求（无 `q`）没有 `must` 子句，`score`/`raw_score` 恒为 `0`——正常现象。
> 高亮字段取自该类型 `WEIGHTS` 去掉 `^boost`，所以新增全文字段（如 `experience.original_publish.text`）会自动进入高亮。

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

**查询构造其他要点**

- `must`：`q` 存在时 `multi_match`（字段用加权字段、`type:best_fields`、`analyzer: ik_smart`）。
- `nested`：凡涉及 `responsibility.*` 或（viewpoint）`reasoning.steps.*` → 用 `nested` 查询包住。
- **`inner_hits`（保留 nested 的原因）**：用户期望"看到命中的那一条"（`responsibility` 哪条 / `reasoning.steps` 哪步）。当请求按 nested 子字段过滤时，nested 查询加 `"inner_hits": {"_source": true}`。**这一步只有 `nested` 能做**，平铺 `object` 无法返回命中元素，故这两处**保留 nested**。
- 高亮：`pre_tags/post_tags = <em>...</em>`，字段取所属索引 multi_match 的字段。
- **聚合/过滤字段（keyword）**：`presentation.period.keyword`、`presentation.region`、`presentation.industry`、`presentation.source_type`、`presentation.publisher`、`experience.original_publish`、`experience.confidence_level`、`identity.status` 等——可对 `filter` 精确筛选，也预留给独立聚合端点；**搜索响应不带 facets**（定稿：纯粹结果）。
- **两个必知坑**：① `period` 有区间值（如 `2023-2027`），`period=2024` 的 term 精确匹配会漏区间——后续加归一化年份字段，当前按精确串匹配并标注。② `terms` 传参：`project_id`/`source_type`/`publisher`/`source_ids`/`evidence_ids` 支持列表（多值），单值亦可。

### 4.2 完整对象 `GET /api/v1/objects/{object_type}/{oirf_id}?project_id=`

回 Mongo 取**完整权威字段**（原样 `_source` 不完整处，如完整 `reasoning`、`responsibility`、`identity` 及未映射长文本）。**`project_id` 缺省仍为 `1`**——本端点按 `oirf_id` 定位，而 `oirf_id` 只在一个项目内唯一。因此从**全局/多项目检索**结果点进详情时，**必须把卡片里的 `project_id` 传回来**，否则会取到项目 1 的同号对象（静默串号）。

### 4.3 关联图谱 `GET /api/v1/associations/{object_type}/{oirf_id}`（**设计定稿 · 未实现**）

> 本节是**设计记录**：接口形状、查询计划、实测边界均已确定，**代码未写**。文中数字全部是在冻结数据（project 1，24/349/24）上的**实测值**，实现后逐条对表即可（§4.3.6）。

#### 4.3.1 关联形状（实测，决定了一切开法）

**关联天然是三层 DAG：`viewpoint → evidence → source`。无环、无反向引用字段。**

| 类型 | 出边字段 | 映射 |
|---|---|---|
| viewpoint | `reasoning.steps[].evidence_ids`、`reasoning.steps[].source_ids` | **nested**（`reasoning.steps`） |
| evidence | `reasoning.source_ids` | keyword |
| source | **无出边** | — |

由此推出两条必须写死的结构结论：

- **`viewpoint` 的 `direction=in` 恒空**（无任何字段引用观点）；**`source` 的 `direction=out` 恒空**。两者与 `hops` 无关（实测 hops=1/2 均为 0）。
- **"`hops` 上限 2"只对单方向成立**：`direction=out` 从观点出发 2 跳到底（实测 V001 `10 → 10`，第 2 跳无新节点）；`direction=in` 从来源出发 2 跳到底（实测 S001 `179 → 179`）。
- ⚠️ **`direction=both` 没有 2 跳天花板**——它会来回弹（证据的入边是别的观点，那些观点又带回自己的证据）。实测扩散曲线一路涨到全库（总量 397）：

  | root | `both` hops 1→6 |
  |---|---|
  | `viewpoint:V001` | 10 → **212** → 269 → 339 → 371 → 374 |
  | `evidence:E005` | 2 → 37 → 212 → 269 → 339 → 371 |
  | `source:S001` | 179 → **253** → 339 → 371 → 374 → 374 |
  | `source:S003` | 3 → 3 → 3 → 3 → 3 → 3（孤立小簇，天然封顶） |

  ⇒ 对 `both` 而言，`hops≤2` 是**成本约定**，不是图论结论。且 `both&hops=2` 的真实语义是"**同源/同证据邻域**"（靠共享证据/来源找到邻近文档），与"这个对象的关联"不是一回事。

**引用完整性（实测）**

| 边 | refs | dangling |
|---|---|---|
| viewpoint → evidence | 236 | **0** |
| viewpoint → source | 59 | **0** |
| evidence → source | 349（349 条证据各恰好 1 个来源，**1:1**） | **0** |

**`steps` 是数组 ⇒ V→E 不是链，而是"每步一个星"**

- 每观点 **1–3 步**，全库共 **53 步**。
- 实例 `viewpoint:V001`：第 0 步 → 4 证据 + 2 来源；第 1 步 → 4 证据 + 1 来源。
- ⚠️ **`step.source_ids` 不能由该步证据推导**：53 步里 **5 步**与"该步证据的来源并集"**不一致**——`V001`(step0/step1)、`V009`(step1)、`V015`(step0/step2)。
  例：V001 step0 声明 `{S001,S002}`，而其证据只回溯到 `{S002}`。
  ⇒ **`step` 归属必须挂在边上，两条边如实并列——不推导、不修补、不合并。**

#### 4.3.2 契约（定稿）

| 约定 | 值 | 依据 |
|---|---|---|
| **`project_id`** | **必填，缺失 → 422**（**不**沿用 §4.2 的缺省 `1`） | `oirf_id` 只项目内唯一，缺省即**静默串号** |
| **返回形态** | **`nodes` + `edges`**，非链 | 见 §4.3.1（steps 数组 + 5/53 冲突） |
| **边方向** | **恒定按语义（引用方向）**；`direction` 只决定从哪端走，反向结果里边仍写作 `from=viewpoint:V001, to=evidence:E005` | 客户端一套渲染代码 |
| **分页** | **不用 `page`/`size`**（子图跨页会碎）；用 `limit` + `truncated` | 见下"体积" |
| **`limit` 桶粒度** | **每个 `(direction, type)` 桶各 `limit`**，**不是**每个 `direction` 一个桶 | 实测：单桶 + 按类型排序 → `limit=50` 时 **50 条全是 evidence，19 个 viewpoint 全丢**（S001 的 `in`，而"谁用了这份材料"正靠 viewpoint 回答） |
| **空引用** | **显式返回 `missing[]`**，不静默丢 | 否则"edges 数 ≠ nodes 数"会被当 bug |
| **`rel` 取值** | 仅 `step_evidence` / `step_source` / `evidence_source` | 就这三条边 |
| **边唯一键** | **`(from, to, rel, step)`** —— 同一对节点在不同 step 下是**两条边** | V001 的 `source:S001` 在第 0、1 步各出现一次：按此键算 **11 条**，若按 `(from,to)` 去重会掉成 **10 条**（丢 step 归属） |
| **`label` 开关** | 跟着 `include` 走：`card` 带、`ref` **不带**（或另给 `labels` 开关） | 实测 `label` 合计 13.3KB ≈ `ref` 载荷的 **28%**；`ref` 场景是"先看图再点开"，边文本可省 |
| **`score`** | 节点**不带 `score`** | 纯遍历无相关度，免得被误当排序用 |
| **nodes 排序** | **确定性**（`object_type, oirf_id`） | 否则两次调用顺序不同，无法 diff 验证 |

**体积（实测）**：单条 `card` 均值 **1158B**（最大 2607B），`ref` 均值 **191B**（最大 267B）——**约 6×**。

| 子图 | 节点 | `card` | `ref` |
|---|---|---|---|
| `viewpoint:V001` `out hops=1` | 10 | 11.3KB | 2.0KB |
| `source:S001` `in hops=1`（=`both hops=1`） | 179 | **209.3KB** | 33.0KB |
| `viewpoint:V001` `both hops=2` | 212 | 242.8KB | 39.3KB |
| `source:S001` `both hops=2` | 253 | **291.6KB** | 47.1KB |

⇒ 必须有 `include`：

- `include=card`（默认）：同 `/search` 的轻卡片字段
- `include=ref`：只给 `id` / `oirf_id` / `object_type` / `project_id` / `identity.name` / `identity.status`
- **建议 `hops=2` 时默认 `ref`**

#### 4.3.3 请求与响应

```http
GET /api/v1/associations/{object_type}/{oirf_id}
      ?project_id=1             # 必填（int）；缺失/非整数 → 422
      &hops=1                   # 1|2，默认 1；上限 2 是成本约定（见 §4.3.1）
      &direction=both           # out|in|both，默认 both
      &types=evidence,source    # 限定**返回**的类型（语义见 §4.3.5）
      &include=card             # card|ref
      &limit=50                 # 每个 (direction, type) 桶上限，max 200
```

```jsonc
{
  "root":  { "id": "…", "oirf_id": "viewpoint:V001", "object_type": "viewpoint", "identity": { } },
  "project_id": 1, "hops": 1, "direction": "both", "include": "card",
  "nodes": [ { "oirf_id": "evidence:E005", "object_type": "evidence", "identity": { } } ],
  "edges": [ {
      "from": "viewpoint:V001", "to": "evidence:E005",
      "rel": "step_evidence", "step": 0, "hop": 1,
      "label": "全球与中国2023年前三季度VR/AR出货量…"   // = steps[].to
  } ],
  "truncated": false,
  "missing": []
}
```

> `label` 取 `steps[].to`：该字段**未映射进 ES 索引**，但完整保存在 `_source` 里（实测 V001 step0 有值）。它是"这一步在说什么"——图谱边上最该显示的内容，白捡的。

#### 4.3.4 查询计划：**ES 单源，0 次 Mongo**

> ⚠️ 这里**修正**了此前"ES 查关联 + Mongo join"的设想：**那个 join 是多余的**。实测 ES `_source` 与 Mongo 文档**除 `_id` 外完全一致**（`mongo-only keys: ['_id']`、`es-only keys: []`），而 `hit_to_card` 只读 `_source` ⇒ 节点卡片直接复用 `app/search/response.py:hit_to_card`，输出与 `/search` **同构**。

**每请求常数次查询，无 N+1：**

| root | 查询 | 次数 |
|---|---|---|
| 任意 | 取 root 自身（顺带拿到它的出边数组） | 1 |
| viewpoint | 出方向：**直接从 `_source.steps` 读数组**，再 `terms` 批量取节点（evidence、source 各 1） | 2 |
| evidence | 出：读 `reasoning.source_ids` → `terms` 取 source；入：`nested` 查 viewpoint | 2 |
| source | 入：`knowledge_evidence` 查 `term reasoning.source_ids`（1）+ `knowledge_viewpoint` 查 `nested reasoning.steps.source_ids`（1） | 2 |

**关键省事点**：**出方向不需要 nested 查询**——邻居 id 就在 root 自己的 `_source` 数组里，读数组 + 一次 `terms` 就够。`nested` 只用于**反向**（"谁引用了我"）：

```jsonc
// 反向：谁引用了 evidence:E005 —— 实测 1 命中
{ "nested": { "path": "reasoning.steps",
              "query": { "term": { "reasoning.steps.evidence_ids": "evidence:E005" } } } }
```

**实现细节**

- 纯遍历无相关度 ⇒ 全部走 `bool.filter`，不取 `_score`。
- **`size = limit + 1`** 判断截断：取到 `limit+1` 条即 `truncated: true`，丢掉多余那条。
- `hops=2` 时对第 1 跳节点集**批量**再查（`terms` 多值），仍是常数次。
- ⚠️ **`hops=2` 必须按 `oirf_id` 去重**：`source:S001` 的"经证据到达的观点"与"step 直接声明的观点"是**同一批 19 个**，朴素相加会把 `199` 算成实际 `180`（多算 19）。

#### 4.3.5 实测边界（必须写明，否则会被当 bug 报）

| 现象 | 实测 | 归因 |
|---|---|---|
| **反向经常空** | 349 条证据**仅 222 条被引用**，**127 条（36%）无任何观点引用**；最大 fan-in = **2** | 数据事实，非缺陷 |
| **正向可能极大** | `source:S001` → **160 条证据**；`source:S003` → 3 条 | 分布极不均，靠 `limit` 兜 |
| **`direction=both` 无跳数天花板** | 扩散到全库（374/397），曲线见 §4.3.1 | 来回弹，非三层 DAG 的向下遍历 |
| **单桶 `limit` 会饿死类型** | `source:S001` `in`：全量 `{evidence 160, viewpoint 19}` → 单桶取 50 = **`{evidence 50}`，观点 0 条** | ⇒ `limit` 必须按 `(direction, type)` 分桶 |
| **`types` 两种语义实测分歧到 0** | 见下表 | ⇒ 推荐"限制返回" |
| **5/53 步来源标注与证据不一致** | V001 / V009 / V015 | 见 §4.3.1，接口如实呈现 |
| viewpoint 无入边 / source 无出边 | `hops=1/2` 均为 0 | 结构使然 |

**`types` 两种语义的实测分歧**（"限制返回"= 先全展开再筛；"限制展开"= 不符类型不进不展开）

| root | direction | hops | `types` | 限制**返回** | 限制**展开** |
|---|---|---|---|---|---|
| `evidence:E005` | both | 2 | `viewpoint` | **3** | 1 |
| `evidence:E005` | both | 2 | `source` | 2 | 1 |
| `source:S001` | both | 2 | `source` | **12** | **0** |
| `viewpoint:V001` | both | 2 | `source` | 2 | 2 |
| `source:S001` | in | 1 | `viewpoint` | 19 | 19 |

> 关键区别是**单调性**："限制返回"下 `types` 越大结果只增不减（可推理）；"限制展开"**非单调**——`source:S001` 传 `types=source` 得 **0**，加上 `evidence` 反而得 **12**，调用方几乎无法预期。
> 所以**推荐"限制返回"**，代价（多展开）用两阶段消掉：**先只取 `oirf_id`（`_source: false`）做 id 层 BFS，筛完再取要返回的节点载荷**。

**未定项（待拍板，2 条）**

1. **`types` 语义**：推荐**限制返回**（依据上表单调性）。若你更看重省查询、接受"加类型反而变多"，则选限制展开。
2. **MVP 范围**：建议先做 `direction=out|in` + `hops=1`（三种 root 全覆盖）。**`both&hops=2` 建议不放进来**——实测 212–253 节点、语义已变成"同源邻域"，与本端点定位不同，适合另开参数/端点。

#### 4.3.6 验收锚点（实现后逐条对表）

```
viewpoint:V001  out hops=1  → evidence 8（去重）/ source 2（去重）/ edges **11**（step0: 4+2, step1: 4+1；`S001` 两步各一条，故 11 而非 10）
viewpoint:V001  out hops=2  → 与 hops=1 相同（10 节点，第 2 跳无新节点）
evidence:E005   out hops=1  → source 1 ；in hops=1 → 被引用 1（viewpoint:V001）
evidence:E005   both hops=1 → 2 ；both hops=2 → 37
source:S001     in  hops=1  → evidence 160 / viewpoint 19（共 179；limit=50 时按 (direction,type) 分桶 = 50 ev + 19 vp，truncated=[in:evidence]）
source:S001     out hops=1  → **0**（source 无出边）
source:S003     in  hops=1  → evidence 3 / viewpoint 0
viewpoint:V001  both hops=2 → 212 节点（evidence 192 / viewpoint 18 / source 2）← 已属"同源邻域"，见未定项 2
缺 project_id → 422 ；不存在的 oirf_id → 404（不是空图）
```

> 以上均在 project 1 冻结数据上实测。**当前库内只有 project 1，跨项目隔离未能实测**——多项目入数据后必须补测"同 `oirf_id` 不同项目不串号"。

**未定项（待拍板，2 条）**

1. **`types` 语义**：限制**展开**还是限制**返回**？`hops=2` 下二者结果不同。建议**限制展开**（否则服务器白取一堆再扔掉）。
2. **MVP 范围**：建议先只做 `hops=1`（三种 root 全覆盖）——`hops=2` 的价值受制于上文"36% 反向空洞"。

---

## 5. 中文分词与检索细节

- **索引侧** `ik_max_word`（最大切分，召回高）；**查询侧** `ik_smart`（粒度粗，精确）。
- **召回松紧 `mode`（已实现）**：三种模式共用同一套字段与权重，只改"命中多少词才算命中"——
  `or`（默认）`multi_match` 默认 `operator=or`；`and` 加 `operator: "and"`；`phrase` 用 `multi_match` 的 `type: "phrase"`（等价严格 `match_phrase`）。
  未知 `mode` 直接报 `ValueError`（不静默退回 `or`），HTTP 层表现为 **422**。
- 宽松模糊匹配：`fuzziness: "AUTO"` —— **仍未实现**（中文短查询下收益不明，暂不做）。
- 过滤/聚合一律用 `keyword` 字段（`term`/`terms`/`aggs`），不参与分析。

> **召回松紧实测（`type=all`，三类合计）**：`空间计算` → or 23 / and 13 / phrase 12；`空间计算设备` → or **73** / and **8** / phrase **8**；
> `zzz不存在词 空间计算` → or **23**（无关词被静默忽略）/ and **0** / phrase **0**。
> 即：默认 `or` 下"搜到 23 条"不代表 23 条都相关——`空间计算` 一个查询词就有 10 条只含「空间」或只含「计算」；
> 要判断"是否真的搜到"，须显式 `mode=and`（`type=all` 的 and 结果 = 三类各自 and 之和：source 3 + evidence 8 + viewpoint 2 = 13）。

> **权重校准（真实数据实测）**：`identity.name` 是精炼主题摘要句，短关键词下最能命中"真正讲这个"的文档；
> `value` 常是长描述或纯数字，权重若高于 name，会把"仅在长描述里碰巧含该词"的跑题文档抬上来（如搜「空间计算」时
> 《三款头显均采用Pancake光学方案》排前）。故 evidence 采用 name 最高。`viewpoint` 的 `presentation.name` 与
> `identity.name` 数据中一字不差（重复内容），加权即重复；`experience.name` 是判断/角度标签（态势判断/归因/格局/
> 成本结构），搜角度词（如「竞争格局」）时须能上位，故给 `^2`。`source` 的 `identity.name` 已是「出版方+标题」，
> 最完整干净，作最高权重。evidence 的 `experience.original_publish.text` 与 `subject.text` 同级 `^2`：来源是强信号，
> 但不该压过内容字段。

> **全文检索 vs 来源筛选（为什么不靠 `q` 找来源）**：`q` 打在分词字段上是 OR 匹配，用来找"来源"既漏又滥——
> evidence 的 349 条材料里，用来源名做 `q` 只能召回 **26 条**（Wind 34 条、知乎专栏 19 条、LEDinside 16 条等
> **13 个来源完全搜不到**），同时多出 **326 条**假阳性（`q=IDC中国高级分析师赵思泉` → 40 条）。
> 所以来源有两条独立通路：`q`（模糊，宽）与 `publisher`（精确，严），二者不冲突且可叠加。

---

## 6. 环境与现状

| 组件 | 容器 / 镜像（以 `docker ps` 为准） | 端口 | 现状（实测） |
|---|---|---|---|
| MongoDB | `mongodb`（mongodb-community-server:latest） | 27017 | 权威库 `knowledge_db`：`sources 24 / evidence 349 / viewpoints 24` |
| Elasticsearch | `es01`（elasticsearch:9.5.3，含 analysis-ik） | 9200 | 三索引 `knowledge_source/evidence/viewpoint`，`_count` 与 Mongo 逐类型一致 |
| Kibana | `kibana`（kibana:9.5.3） | 5601 | Search 主页需 ES 安全；非必需组件 |
| 搜索 API | FastAPI（`python run.py`） | 8000 | 非常驻；起来后 `/docs` 是 OpenAPI 页面 |

**数据现状（实测口径）**：project 1；`id = _id = ObjectId`；ES `_id` 与 Mongo `_id` 一一对应，逐类型 **24/349/24，零漂移**。

**执行位置与编码**：所有命令都要在**仓库根目录**跑（否则 `ModuleNotFoundError: No module named 'app'`）；
Windows PowerShell 下建议先 `$env:PYTHONIOENCODING='utf-8'`，否则输出的中文会显示成乱码。

**容器未起时**：Mongo/ES 都在容器里，未起时搜索会以连接类异常失败（**不会静默成功**）：

| 依赖未起 | 异常 |
|---|---|
| Elasticsearch | `elasticsearch.ConnectionError` |
| MongoDB | `pymongo.errors.ServerSelectionTimeoutError`（`No servers found yet`） |

---

## 7. 待实现 / 风险

| 项 | 状态 | 说明 |
|---|---|---|
| **搜索 API（§4）** | ✅ 已实现并回归 | `POST /api/v1/search`（§4.1）+ `GET /api/v1/objects`（§4.2）。HTTP 路由经 `TestClient` 走真路由回归：字段名与 mapping 全对齐、加权字段均为 `text`、`nested` 关联与 `inner_hits`、翻页一致性、`publisher` 单值/多选/严格语义、`project_id` 各形态（不传/`[]`/单值/数组/`0`）、空结果与非法入参 200/422 分支。`/associations`（§4.3）见下行 |
| **`/associations`（§4.3）** | 📝 **设计定稿 · 未实现** | 契约 11 条、查询计划（**ES 单源、每请求常数次查询、0 次 Mongo**）、实测边界 7 条、`types` 语义对照表、验收锚点 9 条均已写入 §4.3；**2 条未定项**待拍板（`types` 语义推荐"限制返回"、MVP 范围）。实测底座：三层 DAG（`viewpoint→evidence→source`，无环）、三种边 dangling **0**、**127/349 证据反向空洞**、`source:S001` 反向 **179 节点**（card 209KB / ref 33KB）、`direction=both` **无跳数天花板**（扩散至 374/397） |
| **两族筛选语义统一** | ⏳ 待定 | 现在"集合限定族"（严格）与"字段取值族"（忽略）并存（§4.1.2）。语义各自成立，但调用方需要记两张表；将来若统一，需连带评估 `region`/`period` 等参数的行为变化 |
| **`period` 区间过滤** | ⏳ 待做 | `period` 有区间值（如 `2023-2027`），精确筛 `period=2024` 会漏掉区间；后续加归一化年份字段 |
| **聚合 / facets** | ⏳ 待定 | 搜索响应定稿不带 facets；keyword 字段已就绪，需要"来源取值下拉""地区分布"这类前端能力时再加独立端点（`publisher` 的取值列表就是第一批候选） |
| **`sort` 排序参数** | ⏳ 待定 | 当前只能按相关度排序，不支持按时间/名称排序 |
| **深分页** | ⏳ 暂缓 | 当前 `from/size` 够用；量大改用 `search_after`。注意 `type=all` 是"每池取 page×size 再合并切片"，本质有截断 |
| **`type=all` 头部并列** | ⏳ 已知 | 每池归一化后各自的第一名都是 1.0，并列时顺序取决于稳定排序，客户端不应依赖 |
| **内容去重** | ⏳ 暂缓 | 内容重叠少；量级上来再考虑 content-key 去重 |
