# 向量化改造 TODO

对存进 ES 的检索数据做向量化，走 BM25 + 向量混合检索。本文只记决策与待办，动手改代码前先逐项过。

## 0. 前置事实（决策依据）

来自 `example/` 实测，非估算：

| 事实 | 数值 | 影响 |
| --- | --- | --- |
| ES 里现有长文本 | **不在索引里，但在 `_source` 里**。`dynamic: false` 的语义是"未声明字段不索引、不可搜索，但仍保留在 `_source`"；`full_sync` 提交的是整个 Mongo 文档，所以 `raw_texts`/`notes`/`summary`/`content`/`explanation`/`narrative` 全都在 `_source` 中 | 文本已经拿得到，不需要"额外同步"；要改的只是"是否声明为 `text` 以便高亮" |
| 实体全部文本拼接长度 | evidence 中位 54 字 / 最长 202；viewpoint 中位 227 / 最长 292；source 中位 83 / 最长 144 | 远小于 bge-base-zh-v1.5 的 512 token 上限，**不需要切片** |
| 模板常量文本 | `evidence.experience.confidence_reason` 349 条全同；`source.experience.level_reason` 24 条全同 | 拼进向量会造成高密度簇污染 kNN，必须排除 |
| 短字段 | `evidence.presentation.indicator` 中位 4 字、`value` 5 字、`subject` 6 字 | 4~6 字 embedding 表示不稳定且无信息量，且已有 keyword 精确过滤，不向量化 |
| 模型 | 本地已缓存 `BAAI/bge-base-zh-v1.5`，768 维，512 token | mapping 的 `dims` = 768 |

## 1. 整实体向量化

- [x] **决策：拼接哪些文本** —— 已定稿，落在 `embedding/fields.json`

  | 类型 | 进向量 | 拼接后长度 p50 / p90 / max |
  | --- | --- | --- |
  | source | `identity.name` + `presentation.summary` + `presentation.publisher` | 80 / 124 / 142 |
  | evidence | `identity.name` + `presentation.raw_texts` | 46 / 84 / 147 |
  | viewpoint | `identity.name` + `presentation.content` + `presentation.explanation` + `reasoning.steps[].to` + `reasoning.narrative` + `experience.content` | 285 / 371 / **406** |

  字段列表**不写死在代码里**，由 `embedding/fields.json` 声明，embedding 时读取。该文件**只放数据与解析契约**（`$comment` 说明 path 语法、值类型、拼接规则）；**排除清单属于决策，记在本文档的「排除清单」一节，不放进 JSON**——两个名单并存会造出"同一字段里外不一致"这类矛盾。

  两个推翻初稿的实测发现：

  - **source 不用 `presentation.title`，用 `identity.name`**。title 有 18/24 含 SEO 杂质（`_腾讯新闻(qq.com)`、`（附下载）_同比_市场_全球(sohu.com)`），identity.name 只有 2/24，且是"发布方 + 干净标题"。
  - **evidence 不加 `subject`/`indicator` 做弱上下文**。单向量没有字段权重概念，"弱"只能用模板/位置表达；而 subject/indicator（p50 6/4 字）与 identity.name 高度重叠，边际收益接近零。数据里最短的 raw_texts 只有 4~6 字（`IMU3`、`色域75%`），但对应的 identity.name（`IMU单价3美元`）已足够表达。

  已确认无空串：三类共 397 条按规范拼接后均非空。

- [x] **排除清单** —— 从 `embedding/fields.json` 的 `excluded` 节移入本文档

  以下字段经过讨论后**刻意排除，不要加回**。加回前先读理由——大多数理由来自实测数据，不是口味问题。

  | 字段 | 排除理由 |
  | --- | --- |
  | `evidence.experience.confidence_reason` | 349/349 条完全相同（模板常量），会在向量空间里形成高密度簇 |
  | `source.experience.level_reason` | 24/24 条完全相同（模板常量） |
  | `source.presentation.title` | 18/24 含 SEO 杂质（`_腾讯新闻(qq.com)`、`（附下载）_同比_市场_全球(sohu.com)`）；丢掉的实质内容已被 `summary` 覆盖 |
  | `source.presentation.notes` | 文件管理元信息（如"材料包中登记为 材料_PPTX_原稿.pptx"），不是内容 |
  | `evidence.presentation.notes` | 重复度高（51/109 distinct），且多为出处标注 |
  | `evidence.presentation.value` | p50 仅 5 字，多为纯数值；dense 模型对精确数字不敏感 |
  | `evidence.experience.original_publish` | 仅 17 个取值，且已是 filter 字段（`PUBLISHER_FIELD`） |
  | `evidence.presentation.subject` / `indicator` | p50 仅 6/4 字，与 `identity.name` 高度重叠；BM25 已有 `^2`，不构成有效上下文 |
  | `evidence.presentation.period` / `region` / `industry` / `source_type` | 枚举字段，已有 term 精确过滤，重复投入 |
  | `*.experience.confidence_level` / `claim_type` / `applicable_scenario` / `cross_validation_mode` | 枚举字段，已有 term 精确过滤 |
  | `viewpoint.presentation.name` | 与 `identity.name` 在 24/24 条上完全相同；三类实体统一取 `identity.name` |
  | `viewpoint.presentation.change_triggers` | 疑似模板化（"若季度数据被全年数据修订或口径变化，结论需相应调整。"） |
  | `viewpoint.experience.name` | 经验层是**分类维度**，不是"这个观点在讲什么"。分类维度应走 filter；且已在 BM25 `^2` 覆盖。实测（24 条，弱证据）显示单独加 `content` 反而略升区分度，但**再加 `name` 就退回**——与"短标签拉高彼此相似度"的机制一致 |

  判断其他字段时反复用得到的**两条原则**：

  1. **内容维度走向量，分类维度走 filter。** `identity.name` 回答"这个对象叫什么"（身份锚点，一个实体一个）；`experience.name` 回答"这个对象属于哪一类"（分类，应精确筛选而非模糊接近）。原则不是绝对的——`viewpoint.experience.content` 是有意保留的例外，理由见下一条决策。
  2. **BM25 已覆盖的字段不必再进向量。** 短标签、枚举值恰恰是 BM25 词匹配的强项。

- [x] **决策：两处按人工判断加入** —— 与文档建议不一致，以人工判断为准

  - `source.presentation.publisher`：**加入** `types.source`。虽然 23/24 的 publisher 已出现在 `identity.name` 前缀里（重复），但保留可覆盖剩下那 1/24，且代价只有几十个字符。
  - `viewpoint.experience.content`：**加入** `types.viewpoint`（原文一度误写成不存在的 `experience.context`，已修正）。这对应上面的实验方案 B——实测（24 条，弱证据）显示单独加 `content` 反而使平均两两相似度从 0.6147 降到 0.6081，即区分度略升。与建议的"分类维度走向量应走 filter"原则不一致，取舍是：`content` 描述的是"分析什么主题"，与用户查询措辞重叠度高，这部分召回价值被判定为大于原则上的纯度损失。
  - **`experience.name` 仍排除**（见上表）——实验里它把相似度拉回 0.6135，方向不利。

- [x] **决策：排除清单移出 JSON** —— `embedding/fields.json` 的 `excluded` 节已删除，内容并入本文档的「排除清单」表
  - 理由：`fields.json` 只放**数据与解析契约**（`$comment` 说明 path 语法），**决策**放项目文档
  - 附带收益：只剩一个名单后，"同一字段同时出现在进/不进两个名单里"这类矛盾不可能再发生

- [x] **决策：分隔符与标签** —— 用 `\n` 纯拼接，不加字段标签
  - 理由：bge 在自然文本上训练，`主题：X` 这类结构化提示未必更好，且增加不确定性；`\n` 能保留字段边界

- [x] **决策：是否切片**
  - 当前结论：**仍不引入**，但已接近需要重评
  - ⚠️ **原设的 ~400 字重评门槛已被触及**：加入 `experience.content` 后 viewpoint 拼接长度 max 从 379 涨到 **406**（占 512 上限的 79%）。建议把门槛改为「超过 480 字（约 94%）」，或改为按 **token** 而非字符判断——中文近似 1 字 1 token，但数字与英文的比例不同，bge 的 tokenizer 对大段数字会更省
  - 若将来要切，按 schema 结构切（`reasoning.steps[]`、`presentation.raw_texts[]` 是天然原子单元），不按字数盲切
  - 长文本场景的另一条路：换 bge-m3（8192 token），避免切片，但推理慢得多

- [ ] **待实测：bge 的 query 指令前缀**
  - bge-zh 系官方建议 s2p 场景 **query 侧**加前缀（`为这个句子生成表示以用于检索相关文章：`），passage 侧不加
  - 前缀已记在 `embedding/fields.json` 的 `model.query_instruction`
  - 加与不加以本项目数据实测对比后再定

- [x] **读取器与拼接函数** —— 落在 `embedding/spec.py`（`build_text` / `text_hash`）

  实现取「**先把整篇文档扁平化**（数组下标写成 `[]`），**再按 `path` 精确匹配或 `path + "[]"` 前缀匹配**」。不需要递归下降求值器。四条实现契约：

  - **前缀只能是 `path + "[]"`，不能是 `startswith(path)`**。后者会让 `presentation.content` 误吃 `presentation.contents` 之类——安静的错误。
  - **外层遍历 spec 路径、内层遍历文档**。拼接顺序由 spec 决定，不由 JSON 键顺序决定；键顺序若漏进文本就会漏进 hash，"同一份数据换个序列化顺序"会被误判成过期向量。
  - **每个字符串叶子 `strip()`，`None` 丢弃，其余标量 `str()`**。分隔符是构建器唯一引入的空白，hash 才可复现。
  - **数组元素缺子字段要容忍**（某个 `step` 没有 `to` 就什么都不贡献，不报错）。

  ⚠️ **spec 里没写、但必须有的规则：标量列表也要用 `separator` 拼入。** `presentation.raw_texts` 是 `list[str]`，而路径里没有 `[]`。若按普通标量处理，`str()` 会拼出带引号方括号的字符串直接污染向量。**实测 349 条 evidence 的 `raw_texts` 每条都恰好只有 1 个元素**，所以这条分支在当前数据上**永远不会被触发**——属潜伏分支，等第二段 raw_text 出现才第一次生效（`embed_text_hash` 会跟着变，不会静默复用旧向量）。

  核对：`build_text` 复现了上面的长度表（source 80/124/142、evidence 46/84/147、viewpoint 285/371/406），三类共 397 条**无空串**，且 hash **两两不同**（24/349/24 个不同值）。

- [x] **编码器** —— 落在 `embedding/encoder.py`

  - **从本地 snapshot 加载**，不用 repo id。`resolve_snapshot()` 认 `refs/main`，但**先校验 `config.json` + 权重文件存在再信任**——本机 cache 里确实躺着一个残缺 revision（只有 `model.safetensors`），信了它会在 transformers 深处才炸。
  - **懒加载**：`import embedding.spec` 不碰 torch，`Encoder()` 构造免费，模型在首次 `encode_*` 时才载入。
  - **`encode_passages` 不加前缀，`encode_query` 加 `model.query_instruction`**（bge 的 s2p 不对称性）。
  - **`.tolist()` 放在编码器内部**：float32 从源头就进不了 `_bulk`，而不是靠调用方记得转。
  - 实测：768 维、python `float`、L2 范数 `1.0`、语义方向正确（`cos(VR查询, VR文本)=0.65 > cos(VR查询, 空间计算设备文本)=0.43`）。

  ⚠️ **实测：向量不是逐位可复现的。** 同一文本单独编码 vs 放进 batch 里编码，`max_abs_diff = 8.9e-08`；同 batch 组成、同 batch_size、甚至新建 `Encoder` 重载模型都**逐位相同**。差异来自 padding 改变浮点累加顺序，对 kNN 无害（比余弦区分度小 6 个数量级，实测 3 个 query 对 4 篇的排序完全不变）。两个后果：

  - **缓存绝不能靠比对向量是否相等**，必须靠 `embed_text_hash`（这正是 hash 取文本、不取向量的原因）。
  - **"重算一遍再 diff 索引"不能作为校验手段**——除非 batch 组成完全一致。

## 2. 检索修改

### 2.1 Mapping

- [ ] 三个 mapping 加 `dense_vector`
  ```json
  "embedding": { "type": "dense_vector", "dims": 768, "index": true, "similarity": "cosine" }
  ```
  - 注意 `dynamic: false`：新字段不显式声明**不会报错**，只会留在 `_source` 里不建索引 → 向量不进 HNSW，kNN 静默返回 0 条
- [ ] 加 `embed_model` / `embed_rev`（keyword）
- [ ] 加 `embed_text_hash`（keyword）—— 用于判断向量是否过期，**不加则将来只能全量重算**
- [ ] 决策：`_source` 是否排除向量字段
  - 排除可省索引体积，代价是不能只靠 ES 重建向量
  - 现有 `SOURCE_BY_TYPE` 是白名单，向量不会泄进 API 响应，这部分无需改

### 2.2 向量存在哪（澄清）

mapping 里的 `"embedding": {...}` 是**字段声明**，不含数据——和 `"identity.name": {"type":"text"}` 里并没有"空间计算设备"这几个字是一个道理。向量的实际数据来自 **bulk 时提交的文档体**，ES 不会替你算，不写就没有。

提交后 ES 对这个字段做两件事：

1. 原样存进 `_source`（就是那个 768 个浮点的 JSON 数组）
2. 因为 `index: true`，构建 HNSW 近邻图（Lucene 内部结构，不可直接读，kNN 查询用的就是它）

没有第三个位置。具体到项目里，就是往 `full_sync.py` 的 `actions()` 里那个 `src` dict 塞 key：

```python
src["embedding"]       = vector.tolist()   # 768 个 Python float，不能是 numpy float32
src["embed_model"]     = "bge-base-zh-v1.5"
src["embed_text_hash"] = text_hash
```

坑：

- [ ] numpy `float32` 直接塞会抛 `TypeError: Object of type float32 is not JSON serializable`，必须 `.tolist()`
- [ ] 数组长度必须严格等于 `dims`（768），否则 index 报错
- [ ] 忘在 mapping 里声明 → 不报错、不进 HNSW → kNN 永远 0 条且静默（`dynamic: false`）
- [ ] `index: false` 就没有 HNSW，只能 `script_score` 暴力算
- [ ] `_source` 里的向量是明文 JSON 浮点，一个 768 维向量约 15~20KB 文本；当前 397 条约 6~8MB，可忽略。若将来切片成多向量（一条 20 段 = 300KB+）再考虑 `_source.excludes`，但排除后就不能凭 ES 自身重建向量
- [ ] **不建议把向量存进 Mongo**：`full_sync` 是纯拷贝会带过去（省重算），但 `/objects` 直接返回 Mongo 文档（`app/search/objects.py` → `serializers.to_jsonable`），会把 768 个浮点吐给用户，必须显式剔除；而且 `to_jsonable` 对未知类型是原样透传，存了 numpy 类型会在 FastAPI 序列化时才炸
- [ ] 决策：向量是"派生数据"，存 Mongo 与否要在"省重算"和"文档膨胀 + 泄漏风险"之间选

### 2.3 长文本：已可读，是否再声明为可搜索

长文本**已经在 ES 的 `_source` 里**（`dynamic: false` 只阻止建索引，不阻止存储；`full_sync` 提交的是整个 Mongo 文档）。它现在"搜不到、不返回"是另外两个原因：

- 搜不到：mapping 里没声明，没建倒排索引
- 不返回：查询带了 `"source": SOURCE_BY_TYPE[type_]` 白名单（`app/search/fields.py`）

所以不存在"要不要把长文本同步进 ES"的问题，只有：

- [ ] **决策：要不要把 `raw_texts` / `summary` / `content` / `explanation` / `narrative` 声明成 `text`**
  - 要：可以高亮、可以让 BM25 直接检索长文本（召回会变好，但 `WEIGHTS` 权重要重新调，避免长文本淹没短标题）
  - 不要：长文本仅用于**算向量**，检索仍只走卡片字段的 BM25 + 向量
  - 注意 `SOURCE_BY_TYPE` 是显式白名单，声明了也不会自动出现在 `/search` 响应里，要单独决定是否加进去

### 2.4 查询构造 `app/search/query.py`

- [ ] `build_query` 产出顶层 `knn`（`field` / `query_vector` / `k` / `num_candidates` / `filter`），与顶层 `query` 并列
- [ ] kNN 的 `filter` **复用 `FIELD_TYPES` 适用性判断**
  - 否则 `type=all` + `period=2024` 会把 source/viewpoint 通过 kNN 捞回来，破坏"排除"语义
  - 现有 `_applicable_types` 是单一来源，别在向量路径开后门
- [ ] `q` 为空（纯筛选）时**不发 kNN**，挂到已有的 `if q:` 同一条件下
- [ ] 分页：kNN 的 `k` ≥ `from + size`；`num_candidates` ≈ 5~10 × k；`_search_all` 里按 `need = page * size` 给
- [ ] 新增 `EMBED_FIELDS` 表，与 `WEIGHTS` 并列
  - 向量字段**不要**塞进 `WEIGHTS`，会被 highlight 的 `split("^")` 逻辑误伤

### 2.5 响应与文档

- [ ] `highlight` 允许为空（kNN 命中而 BM25 未命中的文档没有高亮）
- [ ] 明确向量缺失文档在 kNN 分支里"隐形"：回填期召回偏低但静默，不报错
- [ ] 更新 `docs/search-api-usage.md` 2.6 / 2.7：`score` / `raw_score` 的语义随融合算法一起改

### 2.6 运行时

- [ ] `requirements.txt` 加 `sentence-transformers`（本机已装 6.0.1）+ torch
- [ ] **模型不塞进 FastAPI 进程**
  - `api_search` 是 sync def，跑在 uvicorn threadpool（默认 40 线程）；一次 forward 数百 ms~数秒，几个并发就能占满线程池，`/objects`、`/associations` 全部卡死
  - 放独立进程/独立服务，或至少 `anyio.to_thread` + 并发限流
- [ ] 可选：`q` 的 query 向量做 LRU 缓存

### 2.7 待讨论：排序策略

现状：`app/search/rank.py` 用 `raw / max_score` 归一后排序。`max_score` 是**单次响应内部**的最大值，翻页时基准变化，同一查询第 2 页分数会跳。纯 BM25 下已是隐患。

加入 kNN 后分数量纲差异更大（cosine 分布集中，BM25 无界 0~40），min-max 会更不稳。

待讨论的选项：

| 方案 | 说明 | 权衡 |
| --- | --- | --- |
| RRF（名次融合） | ES 8.8+ 可用 `rank: {rrf: {}}`，或应用层按名次实现 | 对量纲不敏感、无需调权重；代价是 `score` 语义从"相关度"变"名次分"，文档要改 |
| 加权线性融合 | `α·cosine + (1-α)·norm(bm25)` | 可调优；需要固定归一化基准（不能再用页内 max_score），且 α 要调 |
| ES 原生 `rank` | 交给 ES | 省事；受版本/许可限制，需先确认 |

需要先定：

- [ ] `type=all` 与单 type 是否用同一套融合（现在 `fuse()` 只服务 `type=all`）
- [ ] 单 type 情况下 BM25 + kNN 怎么合（ES 顶层 `knn` + `query` 并列时，两者是独立取 top-k 再合）
- [ ] `score` 对外语义如何定义，是否保留 `raw_score`，是否需要新增 `match_source: bm25 | knn | both`
- [ ] 翻页稳定性：RRF 天然稳定，线性融合需固定归一化基准
- [ ] 是否给 kNN 单独设 `num_candidates` / 权重配置项

## 3. 同步时向量化（挂起）

> 状态：**挂起**，先不实施。等 1、2 落地后按实际数据量重新评估。

已讨论的路线与设计点，先记录备查：

- 三档渐进：
  1. 独立 `vectorize.py` 脚本：按 `embed_text_hash` / `embed_model` 找缺失或过期 → 批量推理 → 只 `_update` 向量字段。幂等、可中断、可重跑。**是所有方案的基础与兜底**
  2. Mongo 侧投递任务 + 常驻 worker：micro-batch（攒 0.5~2s 或 32/64 条）一次 forward。用 Change Stream 需注意 **standalone Mongo 不支持，得先转单节点副本集**
  3. 多写入方/真实时：才考虑 Kafka
- 关键设计点：
  - 写入与向量化**解耦**：先建文档标 `embed_status: pending`，worker 补齐后改状态；检索平滑降级（kNN filter 加 `embed_status: ready`）
  - 绝不同步等模型返回再落 ES
  - 文本 hash 去重 + 向量缓存（模板/枚举重复度高，命中率可观）
  - 攒批是必须的（单条推理不划算）
  - 向量是数组，文本变更需**整体替换**，非追加
  - 模型版本治理：新模型走影子索引 reindex 再切别名；**新旧向量绝不混在同一索引同一字段**
  - 向量当派生数据：可不存 Mongo，但要能凭原文重建
  - 队列项存"待处理的事实"（doc_id + hash），保证重放幂等
  - 背压与优先级：新写入优先，历史回填后排
- 验收标准：把模型进程停掉 10 分钟再启动，系统能自己追上且不重复计算

## 开放问题

- [ ] 是否先只做 viewpoint 试点，验证收益后再推 evidence / source
- [ ] 本地 ES 版本对 nested + dense_vector 的 kNN 支持情况（决定多向量存储方式）
- [ ] 是否引入向量化后需要额外的评测集（现有 `example/` 数据可作为回归基线，但缺少标注的相关性）
