# MongoDB + Elasticsearch 搜索接口方案（Python + FastAPI）

> 目标：把 Docker 里的 MongoDB（authority / OLTP 存储）与 Elasticsearch（全文检索引擎）接起来，
> 对外提供一套知识图谱搜索 API。搜索走 ES，完整对象/关联回 Mongo 补权威字段。

---

## ✅ 阶段状态（已落地 / 待做）

| 阶段 | 状态 | 说明 |
|---|---|---|
| 数据库存储 | ✅ 已落地、锁定 | 权威库 `knowledge_db`；3 集合 `project_id` 分区；`pptx_store` 已弃用 |
| id 模型 | ✅ 已落地 | `id = _id = ObjectId`（全局唯一），**无复合键**；`oirf_id` 仅项目内唯一（`source:S001`） |
| ES 索引 + mapping | ✅ 已落地 | 三索引 `knowledge_*`，`dynamic:false`，见 §3 |
| 同步层（索引 / 全量 / 单条 / 对账 / 种子导入） | ✅ 已落地并实测 | `app/sync` 六个子命令，见 §4；实测 project 1 为 24/349/24、对账零漂移 |
| 搜索 API | ✅ 已实现 | `POST /api/v1/search`（§5.1）+ `GET /api/v1/objects`（§5.2）；本轮只实测了 service 层（直接调用 `app.search.service.search`），HTTP 路由未回归；`/associations`（§5.3）未做 |
| 增量同步触发形态 | ⏳ 待做 | 当前为「写库后显式调用 `sync_one`」（§4.1 ②）；量大再换 Change Streams（§8） |

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
- 全局唯一键 = **`_id`（ObjectId）**；`id` 字段在**导入时**由 `load`（旧的 `ingest.py`）生成：丢弃原始 JSON 的生成期 int `id` → 让 Mongo 自产 `_id` → 回写 `id = _id`。**无需复合键**。
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

## 4. 同步（Mongo ⇒ ES）

两个入口等价、接受同一套子命令与开关（`--help` 里是同一张表）：

```bash
python -m app.sync <子命令>      # 主入口
python full_sync.py <子命令>     # 兼容旧入口（同一份代码，行为完全一致）
```

| 子命令 | 开关 | 作用 |
|---|---|---|
| `init` | — | 按 `mapping/*.json` 建**缺失**的索引；已存在的一律跳过，绝不动索引定义 |
| `full` | `[--recreate] [--dry-run]` | 全量灌 Mongo ⇒ ES；默认不动已有索引，`--recreate` 才删索引重建 |
| `recreate` | `[--dry-run]` | 等价 `full --recreate`：drop → create → 全量重灌 |
| `one` | `--type --oirf-id [--project-id]` | 写库后单条同步；对象已从 Mongo 删除则从 ES 删除 |
| `reconcile` | `[--type] [--fix]` | 对账 ES ↔ Mongo；默认只报告，`--fix` 才删孤儿 + 重灌缺失 |
| `load` | `[--type] [--dry-run] [--prune] [--reset] [--yes] [--no-sync]` | 按 `reasoning/*.json` 增量导入 Mongo（默认只增改、不删），变动顺手推 ES |

> **前置条件**：下面所有命令都要在**仓库根目录**执行（换目录会报 `ModuleNotFoundError: No module named 'app'`）；
> Windows PowerShell 下先执行 `$env:PYTHONIOENCODING='utf-8'`，否则中文输出会乱码（`[ɾ��]`、`[�ع�]`）——
> 那只是控制台编码问题，不是命令失败。

### 4.1 四个基本任务（照抄即可）

当前实测数据：project 1，Mongo `sources 24 / evidence 349 / viewpoints 24`，ES 三索引同值（共 397）。

**① 重建索引 + 全量灌**

```bash
python -m app.sync recreate
```
输出（逐索引列出三段动作，末行是**实际入 ES 条数**）：
```
[删除] knowledge_source
[创建] knowledge_source <- mapping/source_mapping.json
[删除] knowledge_evidence
[创建] knowledge_evidence <- mapping/evidence_mapping.json
[删除] knowledge_viewpoint
[创建] knowledge_viewpoint <- mapping/viewpoint_mapping.json
[重灌] knowledge_source：实际入 ES 24 条
[重灌] knowledge_evidence：实际入 ES 349 条
[重灌] knowledge_viewpoint：实际入 ES 24 条
[完成] 实际入 ES 397 条（Mongo 权威数据未改动）
```

日常只灌数据、**不动索引定义**（最常用）：

```bash
python -m app.sync full
```
输出：
```
[跳过] knowledge_source 已存在，索引定义未改动
[跳过] knowledge_evidence 已存在，索引定义未改动
[跳过] knowledge_viewpoint 已存在，索引定义未改动
[重灌] knowledge_source：实际入 ES 24 条
[重灌] knowledge_evidence：实际入 ES 349 条
[重灌] knowledge_viewpoint：实际入 ES 24 条
[完成] 实际入 ES 397 条（Mongo 权威数据未改动）
```

先看会发生什么、不动手：

```bash
python -m app.sync full --recreate --dry-run
```
输出（三个索引各一行，末行是预演汇总）：
```
[计划] knowledge_source：将删除（当前存在） → 将按 mapping/source_mapping.json 创建 → 将全量重灌（预计写入 24 条，按 Mongo 现有条数）
[计划] knowledge_evidence：将删除（当前存在） → 将按 mapping/evidence_mapping.json 创建 → 将全量重灌（预计写入 349 条，按 Mongo 现有条数）
[计划] knowledge_viewpoint：将删除（当前存在） → 将按 mapping/viewpoint_mapping.json 创建 → 将全量重灌（预计写入 24 条，按 Mongo 现有条数）
[预演] 未执行任何删除/创建/写入
```

**② 改一条数据并立即同步（不重灌全量）**

```bash
# 2.1 改一条：给 evidence:E001 的 identity.name 加后缀（第 2.4 步会还原）
python -c "from app.db import get_db, close; db = get_db(); d = db.evidence.find_one({'project_id': 1, 'oirf_id': 'evidence:E001'}); old = d['identity']['name']; d['identity']['name'] = old + ' 【已改】'; db.evidence.replace_one({'_id': d['_id']}, d); print('旧值:', old); close()"

# 2.2 只同步这一条
python -m app.sync one --type evidence --oirf-id evidence:E001
```
输出：
```
旧值: 空间计算设备包含AR、VR、MR终端
[已同步] knowledge_evidence _id=<ObjectId 字符串> <- Mongo evidence project_id=1 evidence:E001
```

```bash
# 2.3 立刻查 ES：应已是新值
python -c "from app.db import get_es, close; es = get_es(); r = es.search(index='knowledge_evidence', query={'term': {'oirf_id': 'evidence:E001'}}, size=1); print(r['hits']['hits'][0]['_source']['identity']['name']); close()"
```
输出：
```
空间计算设备包含AR、VR、MR终端 【已改】
```

```bash
# 2.4 还原（去掉后缀，再同步一次）
python -c "from app.db import get_db, close; db = get_db(); d = db.evidence.find_one({'project_id': 1, 'oirf_id': 'evidence:E001'}); d['identity']['name'] = d['identity']['name'].replace(' 【已改】', ''); db.evidence.replace_one({'_id': d['_id']}, d); close()"
python -m app.sync one --type evidence --oirf-id evidence:E001
```

> 上面这些一行命令刻意**只用单引号 + 不含 `$`**，所以 bash 与 PowerShell 都能直接粘贴执行（`$set` 之类的写法会在两个 shell 里被当成变量插值而失效）。

> - `one` 内部会 `refresh` 该索引，所以**紧接着查就是新值**，不用等全量、不用重启服务。
> - 对象在 Mongo 里**被删掉**后跑同一个命令，输出变成 `[已删除] …（Mongo 已无该对象）`，ES 中该 `_id` 随之消失（`delete` 命中 404 不报错）；两边都没有时输出 `[无需动作]`，退出码仍为 0。
> - 写库代码里要在写完后立刻生效，就调用同一个函数：`from app.sync.one import sync_one; sync_one(project_id, oirf_id, "evidence")`。

**③ 对账（怀疑两边不一致时）**

```bash
python -m app.sync reconcile
```
一致时：
```
[knowledge_source] Mongo 24 条 / ES 24 条 —— 零漂移
[knowledge_evidence] Mongo 349 条 / ES 349 条 —— 零漂移
[knowledge_viewpoint] Mongo 24 条 / ES 24 条 —— 零漂移
[结论] 零漂移 —— 两边 _id 集合逐类型完全一致
```
有漂移时指名列出 `_id` 并给两边计数：
```
[knowledge_evidence] Mongo 349 条 / ES 350 条
  孤儿（ES 有 Mongo 无） 1 条：
    6a9fbd1b270db0c081be6782
[结论] 漂移 1 处（孤儿 1 / 缺失 0）
       本次只报告、未改任何数据；要清理：python -m app.sync reconcile --fix
```
`--fix` 才会动 ES（删孤儿 + 重灌缺失），修完**自动复核**：

```bash
python -m app.sync reconcile --fix
```
输出（开头还会重印一遍对账明细，末尾两行是修复与复核）：
```
[修复] 已删除孤儿 1 条 / 已重灌缺失 0 条
[复核] 修复后再对账：漂移 0 处（已归零）
```

> `reconcile` 报告模式**永远不写 ES**；`--fix` 是唯一会改 ES 的路径。单类型对账用 `--type evidence`。

**④ 只看索引生命周期**

```bash
python -m app.sync init      # 只建缺失的索引；已存在的输出 [跳过] … 索引定义未改动
```

### 4.2 种子导入 `load`（`reasoning/*.json` ⇒ Mongo）

日常用法（**安全，不需要 `--yes`**）：

```bash
python -m app.sync load --dry-run    # 先看：将新增 / 更新 / 未变各几条
python -m app.sync load              # 落库：只增改、默认不删；变动那几条顺手批量推给 ES
```
输出（当前数据本来就一致时）：
```
[种子] reasoning/*.json 397 条 / Mongo 现状 397 条
        sources: 种子 24、Mongo 24 → 新增 0、更新 0、未变 24
        evidence: 种子 349、Mongo 349 → 新增 0、更新 0、未变 349
        viewpoints: 种子 24、Mongo 24 → 新增 0、更新 0、未变 24
[计划] 新增 0 / 更新 0 / 未变 397（默认不删；要删加 --prune）
[落库] sources：无需改动
...
[完成] Mongo 24/349/24 条；ES 已同步本次变动
       核对两边：python -m app.sync reconcile
```

- 按 `(project_id, oirf_id)` **增量 upsert**：已存在的原地更新（`_id` 不变），缺的才插入
- **内容未变的文档不写库、也不推 ES** ⇒ 可反复跑（上面这次实测 1.6 秒、ES 零写入）
- 只比**种子声明的字段**：Mongo 侧的额外字段不会被比较、也不会被删或被覆盖
- 只把**变动过的那几条**批量推给 ES（实测 397 条：批量 0.24s vs 逐条 26.85s，快 112 倍）
  ⇒ **导入完不需要再跑 `recreate`**

两个开关：

```bash
python -m app.sync load --prune       # 额外删掉 Mongo 里"种子已没有"的文档（ES 同步删）
python -m app.sync load --reset --yes # 旧的清空重灌：drop Mongo 三集合 + 重灌 + 重建重灌 ES
```
> 不加 `--prune` 时，报告会明确指出「Mongo 另有 N 条种子没有的，未处理」，不会闷声不管。
> `--reset` 会**重建 ObjectId**，所以必须跟 ES 一起重建 —— 工具已自动做掉（drop 三索引 → 按 mapping 建 → 全量重灌），跑完两边零漂移。

**旧的 `ingest.py` 仍可用**，它就是 `load --reset` 的兼容包装（`--dry-run` 看计划、`--yes` 才执行、裸跑拒绝）：

```bash
python ingest.py --dry-run    # 只报「将清空哪些集合（含现有条数）/ 将写入多少条」，不动库
python ingest.py              # 不带确认 → 拒绝执行并说明会 drop 谁、怎么确认（退出码 1）
python ingest.py --yes        # 真正执行：重灌 Mongo + 重建重灌 ES
```

### 4.3 实现与口径

- 代码：`app/sync/{admin,full,one,reconcile,load,cli}.py`。常量、连接、BSON 转换分别只来自 `app/config.py`、`app/db.py`、`app/serializers.to_jsonable`（脚本不再自带副本）。
- ES 文档 `_id = str(Mongo _id)`（ObjectId 字符串），全局唯一 ⇒ 全量灌天然幂等 upsert，重跑不递增。
- 计数取自 `bulk` **返回值**（真实入库数），不是 Mongo 的 `count_documents`；失败时打印失败条数与原因，并以退出码 1 结束。
- 写后同步与对账修复都会 `refresh` 相关索引，因此命令报出的数字与随后查 `_count` 一致。

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
- **`type=all`**：对三个索引分别按各自的 multi_match 后合并，**按 max-score 归一化分**（`score/max_score` → 0~1）排序——**不能直接比原始 BM25 `_score`**：不同索引规模 `N` 使 idf 标尺不同（evidence 349 条 vs source/viewpoint 24 条，idf 差 ~2 倍；`_explain` 实测 evidence identity.name idf≈4.15 vs source≈1.97，而 boost 同为 ^3、tf 同为 1），字段/权重拓扑亦异。归一化后各类型同标尺、可比排名；原始分另存 `raw_score` 供调试。调 BM25 `k1/b` 治不了（只管 tf 饱和/长度归一，不碰 idf）。

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

> **关联参数的适用类型**（`source_ids`/`evidence_ids` 是"引用/溯源"关系）：`source_ids` 仅适用 evidence（扁平 `reasoning.source_ids`）与 viewpoint（nested `reasoning.steps.source_ids`）；`evidence_ids` 仅适用 viewpoint。`type=all` 时**只查询适用类型**，不适用的类型直接不查（而非无过滤全量混入）；单类型显式请求若带不适用关联过滤 → 返回空结果。`responsible_role` 三类通用，不裁剪。

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

| 组件 | 容器 / 镜像（以 `docker ps` 为准） | 端口 | 现状（实测） |
|---|---|---|---|
| MongoDB | `mongodb`（mongodb-community-server:latest） | 27017 | 权威库 `knowledge_db`：`sources 24 / evidence 349 / viewpoints 24` |
| Elasticsearch | `es01`（elasticsearch:9.5.3，含 analysis-ik） | 9200 | 三索引 `knowledge_source/evidence/viewpoint`，`_count` 与 Mongo 逐类型一致 |
| Kibana | `kibana`（kibana:9.5.3） | 5601 | Search 主页需 ES 安全；非必需组件 |
| 搜索 API | FastAPI（`python run.py`） | 8000 | 非常驻；起来后 `/docs` 是 OpenAPI 页面 |

**数据现状（实测口径）**：project 1；`id = _id = ObjectId`；ES `_id` 与 Mongo `_id` 一一对应，
`python -m app.sync reconcile` 报**零漂移**（24/349/24）。

**执行位置与编码**：同步命令都要在**仓库根目录**跑（否则 `ModuleNotFoundError: No module named 'app'`）；
Windows PowerShell 下建议先 `$env:PYTHONIOENCODING='utf-8'`，否则命令输出的中文会显示成乱码。

**容器未起时会怎样**：Mongo/ES 都在容器里，未起时同步命令会以连接类异常失败（**不会静默成功**），实测：

| 依赖未起 | 异常 |
|---|---|
| Elasticsearch | `elasticsearch.ConnectionError` |
| MongoDB | `pymongo.errors.ServerSelectionTimeoutError`（`No servers found yet`） |

先起容器，再用一条命令确认两边都通且一致：

```bash
python -m app.sync reconcile      # 期望输出：[结论] 零漂移 —— 两边 _id 集合逐类型完全一致
```

---

## 8. 待实现 / 风险

| 项 | 状态 | 说明 |
|---|---|---|
| **同步层（§4）** | ✅ 已落地并实测 | `init` / `full` / `recreate` / `one` / `reconcile` / `load` 六个子命令；实测：全量连跑两遍均 24/349/24（幂等，且与 ES `_count` 一致）、注入必拒文档时报出失败条数与原因并退出码 1、造孤儿/缺失后 `--fix` 自动复核归零 |
| **搜索 API（§5）** | ✅ 已实现 | `POST /api/v1/search`（§5.1）+ `GET /api/v1/objects`（§5.2）；本轮只实测了 service 层（直接调用 `app.search.service.search`，`q=空间计算` 命中 23 条、nested `inner_hits` 正常），HTTP 路由未做回归；`/associations`（§5.3）未做 |
| **增量同步触发形态** | ⏳ 待做 | 当前是「写库后显式调用 `sync_one`」（§4.1 ②）；量大时换 Change Streams（`pymongo.watch()` 长连接 + 批量缓冲 + 重试） |
| **种子导入（§4.2）** | ✅ 本轮落地并实测 | `load` 增量 upsert：只增改、内容未变则不写库也不推 ES（实测一致时 1.6s、ES 零写入）、只批量推变动过的（397 条 0.24s vs 逐条 26.85s）；`--prune` 显式删且 ES 同步删；`--reset --yes` 保留旧的清空重灌并自动把 ES 一起重建（`ingest.py --yes` 等价） |
| **`reconcile --fix` 效率** | ⏳ 已知 | 重灌缺失是逐条 `sync_one`（每条 refresh 一次索引）；量大时改为批量写入后统一 refresh |
| **有漂移时的退出码** | ⏳ 待定 | 现在 `reconcile` 有漂移仍返回 `exit=0`（漂移=发现，不是失败）；若要拿它当 cron 健康检查，需改成非 0 |
| **`period` 区间过滤** | ⏳ 待做 | `period` 有区间值（如 `2023-2027`），精确筛 `period=2024` 会漏掉区间；后续加归一化年份字段 |
| **内容去重** | ⏳ 暂缓 | 内容重叠少；量级上来再考虑 content-key 去重 |
| **深分页** | ⏳ 暂缓 | 当前 `from/size` 够用；量大改用 `search_after` |