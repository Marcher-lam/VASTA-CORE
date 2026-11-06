# VastaCore 多模态 RAG 原型（examples/rag）

基于 VastaCore「无损证据库 + 派生血缘 + 事件留痕」范式的双层检索增强问答原型。
**零侵入**：只调用 packages/ 现有公共 API，不修改任何平台文件；本目录产物不提交 git。

## 范式：粗筛 + 原始兜底（区别于传统 RAG）

```text
摄入：原始字节入 CAS（sha256 寻址）→ 确定性切块 / VLM caption / MinerU 解析 → 云 embedding
      （全部经 save_derived 落血缘）
查询：L1 向量粗筛 top-k → L2 兜底（邻域 chunk 扩展 + 原图直读给 VLM）
      → 生成带 [n] 引用的回答 → quote 回源包含性核验 → observation.external 留痕
```

索引没有新表：`search_artifacts(source="derived.rag_*")` + `lineage` 重建内存索引
（架构评审预演的「向量索引行 = DerivedAsset」落地形态）。

## 方案 B：图文混排文档（PDF）摄入

```text
PDF 原始字节 → save_artifact
  → MinerU(/tasks 异步 + output 目录取图) → md_content + figures
     ├─ md → save_derived(mineru_md) → 切块（图引用→[图: xxxxxxxx] 占位）→ rag_chunk → embedding
     └─ figure → save_derived(mineru_figure) → VLM caption → rag_caption → embedding
血缘四层：pdf → mineru_figure → rag_caption → rag_embedding
         pdf → mineru_md → rag_chunk → rag_embedding
（figure 的检索命中在引用里记 doc_sha=figure、root_doc_sha=pdf——回溯直达原始 PDF 字节）
```

- MinerU 服务：`~/Desktop/mineru-service`（HTTP 不返回图像字节，figures 从
  `output/<task_id>/<stem>/hybrid_auto/images/` 落盘目录读取，与 md 引用精确对应）
- 解析缓存走血缘：pdf 已有 `mineru_md` 派生则整段跳过（重跑零解析成本）
- 语料：`corpus/demo.pdf`（Attention 论文，真实图表压测）+ `corpus/vastacore_arch.pdf`
  （PIL 合成的中文图文版，`make_pdf_corpus.py` 生成）

## 嵌入选型实测记录（omni-embed-nemotron vs caption 代理）

| 实验 | 结果 | 结论 |
|---|---|---|
| omni：中文 query × 合成架构图 | 目标图 0.108 / 错误图 0.120 / 无关文本 0.128 | 无区分度（合成图 OOD + 中文跨模态弱）|
| omni：英文 query × 论文自然图 | 图 0.46 / 相关文本 0.65 / 无关 0.13 | 有跨模态信号，但同内容文本仍高于图像 |
| qwen3-embedding + VLM caption 代理 | 目标 0.62 / 无关 0.34 | **当前语料最优**，全线采用 |

omni-embed-nemotron（text/image/audio/video → 2048 维统一空间）保留为可选后端
（配置项已留）；nomic-embed 的教训：英文中心模型对中文语料相似度全挤在 0.64-0.69、
零区分度——**嵌入模型选型必须用目标语料实测，不能看榜单**。

## 快速开始

```bash
uv run python -m examples.rag.make_figures   # 生成合成架构图语料（一次性）
uv run python -m examples.rag.run ingest     # 摄入（幂等；重跑跳过已入库项）
uv run python -m examples.rag.run query "AD-14 的租户语义是什么"
uv run python -m examples.rag.run eval       # 评测 + 消融（重跑走缓存，零 API）
```

模型端点（OpenAI 兼容，本地 LM Studio）经环境变量覆盖：
`RAG_BASE_URL / RAG_EMBED_MODEL / RAG_VLM_MODEL / RAG_API_KEY / RAG_STORE_ROOT / RAG_TOP_K / RAG_MIN_SIM`

## 模型响应缓存

每次 embedding / VLM 调用以「请求哈希 → 实体索引 rag_model_call → CAS 工件」缓存
（只存本质字段，剥离 id/created）。评测重跑零 API 调用、逐字节可复现。

## 评测

`qa_set.json` 三层 16 题：T 纯文本 / I 纯图像（合成架构图）/ X 跨模态。
指标：recall@k（粗筛）、引用命中率（可溯源核心主张）、关键词覆盖（客观）、
LLM 裁判 1-5（与生成同端点，自评偏差已知，报告标注）。
消融开关：`full`（L1+L2 兜底）vs `l1only`（孤立 chunk、无原图）——直接量化
「延迟压缩 / 原始兜底」假设的增益。

## 评测终版数字（27b 生成+裁判，21 题 × 2 模式，全本地推理，零失败）

| 指标 | full（L1+L2 兜底） | l1only | Δ |
|---|---|---|---|
| recall@10 | 0.905 | 0.905 | —（同层，一致性校验 ✓） |
| 引用命中率 | 0.810 | 0.810 | — |
| 关键词覆盖率 | **0.952** | 0.821 | **+13.1pp** |
| LLM 裁判 | **4.33**/5 | 4.14/5 | +0.19 |

分层裁判：X 跨模态 full 领先最大（4.33 vs 3.67，+0.67——原图直读的价值所在）；
P 层（PDF 图文混排）引用命中 100%、recall 100%。首轮评测「full 反而更差」
是上下文装配 bug（不相邻 chunk 合并出的巨块吃光预算），修复后反超。
已知口径瑕疵：T04/T05/I01/I02 的 cite 误判多为「同内容多副本」工件
（SPINE 正文 / plan.md 复述 / 独立 PNG / PDF 抽取副本，答案引用了语义等价
但不在 gold 集里的源）；P02（论文图 1 标题）是唯一真实质量缺口。

## 诚实边界

- 纯 Python 余弦只够原型规模；chunk 过万 → 毕业为 vasta-storage 的
  VectorIndexMixin（sqlite-vec / pgvector，见 ARCHITECTURE-SPINE Deferred）
- corpus/ 下三张架构图为合成语料（docs/ 本身无图），内容转录自 ARCHITECTURE-SPINE
- quote 包含性核验是玩具级；正式路径是接 Verifier 协议（四态）
- 语料布局变化会使旧 chunk 的 index/total 过期（lineage.conflict 跳过策略）；
  彻底重来请换 RAG_STORE_ROOT
- VLM 是思考型模型（reasoning 吃 max_tokens 预算）；配置默认 2500
