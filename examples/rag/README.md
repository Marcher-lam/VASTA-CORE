# VastaCore 多模态 RAG（examples/rag）

基于 VastaCore「无损证据库 + 派生血缘 + 事件留痕」范式的**双层检索增强问答原型**：
L1 向量粗筛定位候选，L2 回链原始证据（邻域原文扩展 + 原图直读）生成可溯源回答。

- **零侵入**：只调用 `packages/` 现有公共 API，不修改任何平台文件
- **多模态**：markdown 文本 / 独立图像 / **图文混排 PDF**（MinerU 解析）三类语料
- **全链路可溯源**：任何答案引用可一键回溯到原始字节（sha256 + 血缘）
- **已评测**：21 题 × 2 模式消融，全本地推理，X 跨模态层 L2 兜底 +0.67 裁判分

本目录代码已入库；运行数据（`.vasta-rag/`）在 `.gitignore` 中。设计决策详见
[DESIGN.md](DESIGN.md)。

## 架构总览

```text
──────────── 摄入（幂等，可增量）────────────
md/txt  ─▶ save_artifact ─▶ 确定性切块 ─▶ rag_chunk ──┐
图像    ─▶ save_artifact ─▶ VLM caption ─▶ rag_caption ─┼─▶ embedding ─▶ rag_embedding
PDF     ─▶ save_artifact ─▶ MinerU 解析                │
             ├─ md ─▶ mineru_md ─▶ 切块（图占位）─▶ rag_chunk ─┘
             └─ figures ─▶ mineru_figure ─▶ VLM caption ─▶ rag_caption ─▶ embedding

──────────── 查询（每次）────────────
query ─▶ embedding ─▶ L1 余弦粗筛 top-k（纯 Python）
      ─▶ L2 兜底：邻域 chunk 扩展 ｜ 图像候选附原图 ｜ chunk 图标记机械附图 ｜ figure 反查文字上下文
      ─▶ VLM 生成 {answer, citations[quote]} ─▶ quote 回源包含性核验
      ─▶ 答案落 CAS + observation.external 事件留痕

血缘四层（PDF 路径）：pdf → mineru_figure → rag_caption → rag_embedding
                    pdf → mineru_md    → rag_chunk    → rag_embedding
```

**索引没有新表**：`search_artifacts(source="derived.rag_*")` + `lineage` 两跳重建内存索引——
架构评审预演的「向量索引行 = DerivedAsset」落地形态。

**图文对齐三层机制**：位置对齐（MinerU 版面顺序 → 图注/讨论段天然同 chunk）＋
身份对齐（`[图: xxxxxxxx]` 占位标记 ↔ `fig_by_prefix`/`chunks_by_fig` 双向映射，
检索时机械联动附图/拉文字）＋ 双通道独立索引（图文各自可召回，装配层会师）。
详见 [DESIGN.md](DESIGN.md#图文对齐三层机制)。

## 快速开始

```bash
# 前置：本地 LM Studio（OpenAI 兼容，默认 127.0.0.1:1234）
#   已加载：text-embedding-qwen3-embedding-0.6b + qwen3.8-27b-mlx
# PDF 语料还需 MinerU 服务（~/Desktop/mineru-service，默认 18000）

uv run python -m examples.rag.make_figures     # 生成合成架构图语料（一次性）
uv run python -m examples.rag.make_pdf_corpus # 生成合成中文图文 PDF（一次性）
uv run python -m examples.rag.run ingest      # 摄入默认语料（幂等；重跑跳过已入库项）
uv run python -m examples.rag.run query "AD-14 的租户语义是什么"
uv run python -m examples.rag.run query "..." --mode l1only   # 消融：仅 L1
uv run python -m examples.rag.run eval        # 评测 + 消融（模型响应走缓存，重跑零 API）
```

## 使用手册

### CLI 子命令

| 命令 | 作用 |
|---|---|
| `run ingest [--corpus a,b]` | 摄入语料（默认见下；逗号分隔路径可覆盖） |
| `run query <问题> [--mode full\|l1only]` | 双层检索问答，打印答案 + 引用 + 核验标记 |
| `run eval [--tiers T,I,X,P]` | 评测 + 消融，报告落 `.vasta-rag/reports/` |
| `run config` | 打印生效配置 |

### 环境变量（全部可选）

| 变量 | 默认 | 说明 |
|---|---|---|
| `RAG_BASE_URL` | `http://127.0.0.1:1234/v1` | LM Studio OpenAI 兼容端点 |
| `RAG_EMBED_MODEL` | `text-embedding-qwen3-embedding-0.6b` | 嵌入模型（1024 维，中文实测最优） |
| `RAG_VLM_MODEL` | `qwen3.8-27b-mlx` | 生成/裁判/caption 模型 |
| `RAG_API_KEY` | 空 | BYOK，仅环境变量，不落库不进日志 |
| `RAG_MINERU_URL` / `RAG_MINERU_OUTPUT` | `18000` / `~/Desktop/mineru-service/output` | MinerU 服务与落盘产物目录 |
| `RAG_STORE_ROOT` | `<repo>/.vasta-rag` | 存储根（换新目录 = 彻底重建索引） |
| `RAG_TOP_K` / `RAG_MIN_SIM` | `10` / `0.25` | L1 粗筛参数 |

### 语料

默认语料：`README.md`、`docs/quickstart.md`、`ARCHITECTURE-SPINE.md`、`prd.md`、
`plan.md`、`VASTA-BRAINSTORM.md` + `corpus/`（3 张合成架构图、Attention 论文 PDF、
合成中文图文 PDF）。换自己的语料：`--corpus my/dir,doc.md`（按扩展名分流：
md/txt→文本，png/jpg→图像，pdf→MinerU 管道）。

### 项目结构

| 文件 | 职责 |
|---|---|
| `config.py` | 配置（dataclass + 环境变量）与语料展开 |
| `cloud.py` | OpenAI 兼容客户端（embedding/VLM）+ 响应缓存 + LM Studio 自愈 |
| `figparse.py` | MinerU 集成（异步任务 + figures 落盘目录双通道） |
| `ingest.py` | 摄入管道（切块 / caption / PDF 分支 / 派生链 / 事件） |
| `index.py` | 索引重建 + 余弦检索 + 窗口合并 + 图文对齐映射 |
| `query.py` | 双层检索 + 上下文装配 + 引用核验 + 事件留痕 |
| `eval.py` | 四指标 + 消融 + LLM 裁判 + 报告落盘（逐题容错） |
| `events.py` | run_id 分配 + EventSequencer 封装 |
| `run.py` | CLI |
| `make_figures.py` / `make_pdf_corpus.py` | 合成语料生成器 |
| `qa_set.json` | 评测集（21 题，四层） |

## 零侵入了平台的什么（复用清单）

| 平台能力 | API | 本项目用法 |
|---|---|---|
| CAS 原始字节 | `save_artifact` / `get_artifact` | 一切载荷的唯一入口（AD-3） |
| 派生血缘 | `save_derived` / `lineage` | 派生链 = 索引结构 + 解析缓存 |
| 结构化检索 | `search_artifacts` / `search_by_entity` | 按 transform 枚举索引行；实体索引当响应缓存表 |
| 事件留痕 | `EventSequencer` | run/artifact/observation 全走现有目录类型（不开新族） |
| 内容寻址幂等 | sha256 天然语义 | 重跑跳过、缓存命中、多代 embedding 隔离 |

## 评测

QA 集 21 题、四层：**T** 纯文本（9）/ **I** 纯图像（4）/ **X** 跨模态（3）/ **P** 图文 PDF（5）。
指标：recall@10（粗筛层，独立于生成）、引用命中率（doc_sha/root_doc_sha ∈ gold）、
关键词覆盖率（客观）、LLM 裁判 1-5（与生成同端点，自评偏差已知）。
消融：`full`（L1+L2 兜底）vs `l1only`（孤立 chunk、无原图、无对齐联动）。

### 终版数字（27b 生成+裁判，21 题 × 2 模式，全本地推理，零失败）

| 指标 | full | l1only | Δ |
|---|---|---|---|
| recall@10 | 0.905 | 0.905 | —（同层，一致性校验 ✓） |
| 引用命中率 | 0.810 | 0.810 | — |
| 关键词覆盖率 | **0.952** | 0.821 | **+13.1pp** |
| LLM 裁判 | **4.33**/5 | 4.14/5 | +0.19 |

分层裁判：X 跨模态 +0.67（4.33 vs 3.67，原图直读的价值所在）；P 层引用命中与
recall 均 100%；I 层 l1only 略优（4.75 vs 4.50）——合成图关键信息 caption 已完整
转述，**L2 原图的价值在图文互证（X 层），不在单图复述（I 层）**。
首轮评测「full 反而更差」是上下文装配 bug（不相邻 chunk 合并巨块吃光预算），
修复后全面反超。已知口径瑕疵：T04/T05/I01/I02 的 cite 误判多为「同内容多副本」
工件（SPINE/plan.md 复述/独立 PNG/PDF 副本，引用了语义等价但不在 gold 集的源）；
P02（论文图 1 标题）是唯一真实质量缺口。

## 模型选型与画像（全部实测，教训入档）

### 嵌入模型

| 模型 | 实测 | 结论 |
|---|---|---|
| nomic-embed-text-v1.5 | 中文相似度全挤 0.64-0.69，零区分度 | 英文中心模型，中文语料不可用 |
| omni-embed-nemotron-3b | 中文 query×合成图 0.108≈噪声 0.128；英文 query×论文自然图 0.46（同内容文本 0.65） | 全模态统一空间对 OOD 图形失效；自然图可用但文本恒占优——保留为可选后端 |
| **qwen3-embedding-0.6b** | 目标 0.62 vs 无关 0.34，干净分离 | **现行主力** |

**硬结论：嵌入模型选型必须用目标语料实测，不能看榜单。**

### 生成模型（LM Studio 本地）

| 模型 | 画像 | 适用 |
|---|---|---|
| **qwen3.8-27b-mlx** | 稳定可靠（长材料不退化），~13 tok/s（干净内存） | 生成/裁判/caption 主力 |
| qwen3.5-9b-mlx | 快（~20-39 tok/s），但长中文材料思考必然退化（2200+6600 token 全耗尽仍零输出，四种禁思考姿势均无效） | 仅短 prompt（caption 可用） |

### caption 代理 vs 直接图像嵌入

caption（VLM 描述）+ 文本嵌入的组合在两种语料上均优于直接图像嵌入——图像的信息
瓶颈在描述质量，而 27b caption 对架构图的转述准确率很高（框内文字、箭头标注全出）。

## 运维与排障

`cloud.py` 内置三层自愈（长评测在本地推理服务上的必需品）：

| 故障 | 症状 | 自愈 |
|---|---|---|
| 内存压力逐出模型 | `HTTP 400 Model unloaded` | 自动 `lms load` 重载后重试 |
| 思考模型偶发长推理 | `finish=length` 空 content | max_tokens ×3 重试 + 超时随 token 缩放 |
| 客户端断连后僵尸生成堵队 | 后续请求全排队超时 | 超时 → `lms unload`（清队列）→ 重载 → 重试 |

其他注意：评测日志落 `.vasta-rag/logs/`（不放 /tmp，会被系统清）；三个大服务
（LM Studio + MinerU + omni）同时驻留内存会互拖速度，用完即停。

## 已知边界与毕业路线

| 边界 | 毕业触发条件 | 去向 |
|---|---|---|
| 纯 Python 余弦线性扫 | chunk 过万或延迟不可接受 | `vasta-storage` VectorIndexMixin（sqlite-vec / pgvector，ARCHITECTURE-SPINE 已预演） |
| quote 包含性核验（玩具级） | 需要语义级核验 | 接 `Verifier` 协议（四态） |
| `examples/` 内原型形态 | 平台化决策 | 检索层进 storage、deriver 进 sdk、多模态 parts 进 protocols（minor） |
| 同内容多副本的引用判分 | 评测口径需要更严 | gold 集纳入全部副本，或按引用文本含 gold 关键词判分 |
| rerank 缺位 | 引用命中率需要更高 | 集成件（候选 10→3 精排） |

运行数据与报告：`.vasta-rag/`（store.db + CAS objects + reports + logs）。
