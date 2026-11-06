# 设计文档 — VastaCore 多模态 RAG 原型

> 配套 [README.md](README.md)（使用手册与评测数字）。本文记录**为什么这样设计**：
> 决策、备选方案与实测证据。

## 1. 目标与非目标

**目标**：在 VastaCore 之上验证「证据优先、延迟压缩」的双层检索范式——
原始证据无损入库，向量/摘要只做粗筛，回答前回链原始证据（原文邻域 / 原图字节）
二次确认，全程血缘可溯源、事件留痕。覆盖三类语料（md / 图像 / 图文混排 PDF）。

**非目标**（对齐平台 PRD §5 与 plan §19.3）：
- 不自研向量库 / OCR 管道——检索、解析、向量化一律集成件
- 不追求生产级吞吐——原型规模（数百 chunk）纯 Python 足够
- 不做 rerank / 认知层闭环（Claim 图接入）——留作后续，接口已预留

## 2. 设计决策

### D1 双层范式（L1 粗筛 + L2 原始兜底），不做传统全量索引管道

- **决策**：向量只用于定位候选；生成上下文由 L2 从原始证据装配
  （邻域 chunk 扩展、原图直读、图标记机械附图）。
- **理由**：VastaCore 的差异化主张就是「证据不早熟压缩」（VASTA-BRAINSTORM：
  摘要定位候选 + 按需拉原始高分辨率片段二次确认，防摘要幻觉）。普通 RAG 在
  ingest 时压缩即永久丢失细粒度证据。
- **证据**：消融实验 X 跨模态层 full 4.33 vs l1only 3.67（+0.67）；关键词覆盖
  +13.1pp（邻域扩展补全被孤立 chunk 截断的事实）。首轮「full 更差」的假象
  是装配 bug，见 D7。
- **备选**：传统 parse→chunk→embed→top-k→generate（被否——丢平台卖点，
  与直接用 LangChain 无异）；「先传统后演进」（被否——ingest 丢原文的实现惯性
  难以逆转）。

### D2 派生链即索引——不建向量表

- **决策**：embedding 是 `transform="rag_embedding"` 的派生工件；索引重建 =
  `search_artifacts(source="derived.rag_*")` 枚举 + `lineage` 两跳回溯。
- **理由**：血缘、租户语义（AD-14）、幂等、多代隔离（transformer_version 过滤）
  全部平台原生；架构评审已预演「向量索引行 = DerivedAsset」的多租户语义。
- **代价**：查询时内存重建、线性扫——原型规模 <1s，是可接受的换血价格。

### D3 实体索引当「请求哈希 → 响应工件」缓存表

- **决策**：模型调用以 sha256(规范化请求) 为实体值登记（`entities={"rag_model_call":
  key}`），命中即读 CAS 工件、不再调 API。
- **理由**：内容寻址要求 sha == 载荷哈希，请求哈希做不到——实体索引正是平台
  现成的二级查找表，AD-2 合规、零侧车文件。收益：评测重跑零 API、逐字节可复现。
- **被否备选**：store_root 下旁车 JSON 目录（违反 AD-2 精神）。

### D4 血缘当解析缓存——MinerU 重跑零成本

- **决策**：PDF 已有 `mineru_md` 派生（`_existing_pdf_parse` 经实体索引一跳血缘
  反查）则整段跳过解析，md 与 figures 直接读回 CAS。
- **理由**：MinerU hybrid-engine 全文解析以分钟计；血缘幂等语义免费获得缓存。

### D5 图文对齐三层机制（装配层对齐，非嵌入层）

```text
第 1 层 位置对齐：MinerU 按版面顺序产 md，图引用落在原始位置
        → 图注行/讨论段与图天然同 chunk（±1 邻域合并带全）
第 2 层 身份对齐：摄入时 ![](images/x.jpg) → [图: xxxxxxxx] 占位，
        caption params.figure 存全名；索引建双向映射：
        fig_by_prefix（标记→图像条目）/ chunks_by_fig（figure→引用它的文本）
        检索时：文本候选的标记机械附原图；图像候选反查文字上下文
第 3 层 双通道独立索引：chunk 与 caption 各自可召回，装配层会师——
        单侧失灵不塌方
```

- **理由**：嵌入统一空间对 OOD 图形失效（D8 实测）；装配层联动零模型成本、
  可解释（每步能指出「这块文本为什么带这张图」）、对齐关系可溯源。
- **注意**：MinerU 图名 ≠ jpg 字节哈希（实测证伪），标记必须经 caption params
  的 figure 名做桥，不能当 CAS 地址直接用。

### D6 事件全走现有目录类型

- **决策**：只用 `run.created/completed`、`artifact.registered`、
  `observation.external`；run_id 冲突自动加后缀（`new_sequencer`）。
- **理由**：13 族封闭集新增族要 protocols minor + E0 评审（ARCHITECTURE-SPINE
  一致性约定）；原型不该动协议层。

### D7 上下文装配：连续段切组 + 单块上限

- **决策**：同文档候选按「连续 index 段」分组扩展（±merge_window），每块截断
  至 2600 字符、总预算 12000。
- **理由**：初版把同文档不相邻 chunk 的整段区间拉进一个巨块（三万字符），第一个
  块吃光预算，把含答案的小块挤出上下文——导致首轮评测 full 反而全面差于
  l1only（T07-T09 全灭）。切组 + 上限修复后全面反超。**教训：消融结果的异常
  优先怀疑实现 bug，其次才是范式假设。**

### D8 模型选型必须目标语料实测（三条实测结论）

1. nomic-embed（英文中心）：中文相似度 0.64-0.69 全挤、零区分度——榜单 unusable
2. omni-embed-nemotron（全模态统一空间）：合成架构图 OOD（0.108≈噪声 0.128）；
   自然论文图有信号（0.46）但同内容文本恒占优（0.65）→ 不做检索主通道
3. caption 代理（VLM 描述 + 文本嵌入）：两种语料均最优（0.62 vs 0.34）
   → **现行方案**；图像信息瓶颈在描述质量，27b 对架构图转述准确率高

生成模型画像：27b 稳定 ~13 tok/s；9b 快但长中文材料思考必然退化
（2200+6600 token 全耗尽零输出，`enable_think`/`enable_thinking`/
`reasoning.enabled` 四姿势均无效）——只配短 prompt。

## 3. 数据模型

### transform 家族（derived_assets）

| transform | 载荷 | source | params 关键字段 | 产出者 |
|---|---|---|---|---|
| `mineru_md` | 解析 markdown | pdf | path, backend | ingest(PDF) |
| `mineru_figure` | 抽取图像字节 | pdf | path, figure | ingest(PDF) |
| `rag_chunk` | 切块文本（面包屑前缀） | doc/pdf | path, index, total, heading | ingest |
| `rag_caption` | VLM 图述 | image/figure | path(, figure) | ingest |
| `rag_embedding` | `{vector, dim, method}` JSON | chunk/caption | model, dim | ingest |
| `rag.model_call`（artifact source） | 模型响应本质字段 | —（非派生） | 实体键 rag_model_call=请求哈希 | cloud |

### 事件使用清单（全部既有目录类型）

`run.created`（摄入/查询/评测各一 run）· `artifact.registered`（每个原始文档）
· `observation.external`（每次查询：问题/mode/引用/答案工件哈希）
· `run.completed`（计数汇总）

## 4. 评测设计

- **QA 集**：21 题 × gold_sources（仓库相对路径→doc sha）× gold_keywords，四层
  （T 文本 9 / I 图像 4 / X 跨模态 3 / P 图文 PDF 5）
- **指标**：recall@10（粗筛独立度量）｜引用命中率（doc_sha ∪ root_doc_sha ∈ gold，
  PDF figure 命中记根源）｜关键词覆盖（客观）｜LLM 裁判 1-5（同端点自评偏差已知）
- **消融**：full vs l1only 同题对照，模型响应全缓存 → 重跑零成本
- **逐题容错**：单题失败记零分续跑（本地推理服务不稳定的必需品）
- 终版数字与口径瑕疵见 [README.md](README.md#评测)

## 5. 毕业路线（原型 → 平台）

| 信号 | 动作 |
|---|---|
| chunk > ~1 万 / 延迟不可接受 | 向量索引毕业为 `vasta-storage` VectorIndexMixin（sqlite-vec 本地档 / pgvector Team 档） |
| 需要语义级引用核验 | quote 包含性检查 → `Verifier` 协议（pass/deviation/inconclusive/system_error 四态） |
| 需要多模态消息结构 | protocols minor 加可选 `parts` 字段；本原型 example-local 客户端改实现 ModelAdapter 进 ModelRouter |
| RAG 需求平台化 | deriver 注册进 `vasta-protocols` DeriverRegistry 挂真实模型；检索面进 storage；认知层闭环（检索结论进 Claim 图、冲突检测、置信衰减）启动 |
| 引用命中率瓶颈确认 | 集成 rerank（候选 10→3 精排） |
