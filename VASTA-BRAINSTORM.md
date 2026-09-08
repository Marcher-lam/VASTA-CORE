<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# VISTA 及同类 ARC-AGI-3 交互式智能体项目调研

VISTA 是斯坦福/伯克利团队(Impossible Research圈)提出的一个**极简视觉Agent Harness**——用原始PNG图像感知、自由语言推理、无损视觉记忆三个组件,让Claude Opus 5等通用多模态模型在ARC-AGI-3的25个公开交互游戏上达到100%胜率和满分RHAE(相对人类动作效率),且不依赖程序合成。这类"给通用模型设计最小化交互外壳,让它在未知世界里自主探索"的研究路线,目前已经形成一个活跃的小生态,可以分成三条主线。[^1_1]

## 程序化世界模型路线

这一路线的核心思路与VISTA相反:让Agent把交互轨迹**蒸馏成可执行代码**(状态表示+转移规则),再在代码模拟器里做搜索规划,而不是让模型直接在语言里"模糊推理"。


| 项目 | 团队/作者 | 核心机制 | ARC-AGI-3公开集得分 |
| :-- | :-- | :-- | :-- |
| **Tycho** | Jens Lehmann, Andrei Aioanei, Sahar Vahdati | 每局游戏维护一条持续对话,可将"经过反证测试"的可执行世界模型委托给Builder做规划 | 100.0%(Opus 5 / GPT-5.6 Sol均达100)[^1_2][^1_3] |
| **Schema** | Zeng, Wang, Ma等(Impossible Research) | 联合求解"状态落地"与"机制发现"两个子问题,把世界模型编码为可运行的`step()`程序,用`run_backtest`对全部历史做验证式回放 | 98.98%(Opus 4.8/Fable 5),95.35%(GPT-5.6 Sol)[^1_4] |
| **Retrodict** | Ryan Brown | 记录每一帧,要求任何规则假设必须先能"逆向重现"已记录的历史,才允许消耗真实动作 | 99.9%[^1_2] |
| **baseline1** | Sergey Rodionov | Coding Agent构建并验证可执行Python世界模型后再规划 | 99.0%[^1_2] |
| **NOOA (NVIDIA-labs)** | Kaplun, Sarafian, Furgale等 | 通用CodeAct Agent,构建可复用NumPy世界模型辅助函数,通过Markdown知识文件持久化学习 | 85.1%[^1_2] |
| **OPINE-World** | Courtis, Li, Sanner等(D3M Lab) | CEGIS风格双Agent博弈:一个负责行动,另一个对抗性重写并测试可执行游戏引擎 | 78.4%[^1_2] |
| **Polyphony Agent** | Yu, Su, Zhao等 | Coding Agent为每局游戏生长出可读的Python"启发式系统"(状态/动态/规划/动作选择) | 19.8%[^1_2] |
| **DreamTeam** | Sarafian, Kaplun, Banner, Soudry, Ginsburg | 六个固定角色的Agent通过共享文件工作区协作构建运行时世界模型 | 38.1%[^1_2] |

## 直接交互/视觉感知路线(与VISTA同族)

这条路线更接近VISTA的哲学:不做程序合成,直接让模型看原始观测、用自然语言维护理解、靠长时记忆机制支撑长程任务。

**NVIDIA AVO** 是最直接的对标项目。NVIDIA将其最初为GPU kernel优化设计的通用长程Agent架构(持久记忆+监督器+执行循环)迁移到ARC-AGI-3,采用VISTA式的直接交互设计原则(自己重新实现任务接口),但观测方式改为纯文本64×64网格而非图像,用Claude Opus 5达到100.00 RHAE,只用了6,624次动作(比VISTA的7,542次少约12%)。该团队论文明确将VISTA列为最重要的对照工作。[^1_5]

**Claude Plays Pokémon**系列是这一路线的先驱和延伸,思路是"截图感知→决策→按键"的简单闭环,不读游戏内存、不做寻路辅助:

- Anthropic官方的Twitch直播项目由David Hershey主导,让Claude(3.7 Sonnet→Opus 4)仅凭截图+可编辑记事本通关Pokémon Red。[^1_6][^1_7]
- Opus 4.7版本新增了"区域放大查看"和"视觉片段存档"两个工具,本质上就是VISTA强调的**无损视觉记忆**思路的早期雏形。[^1_8]
- Claude Fable 5据报道已能纯靠视觉(无地图、无导航辅助)通关Pokémon FireRed。[^1_9]
- 社区复刻版如`Claude-Plays-Pokemon`(LeePresswood)和`pokemon-vision-agent`(QingzeHu)均采用相同的"截图→按键→自记笔记"极简架构。[^1_6]


## 官方基线与其他Agent Harness

ARC Prize官方本身也维护了对照基线(无程序合成的Opus 5高推理档得分约30.16,GPT-5.6 Sol约13.33),以及社区排行榜上的其它探索:[^1_1]

- **Continual Harness**(Feng, Karten, Li等):自改进的ARC-AGI-3 orchestrator,内含Refiner模块根据轨迹证据重写基础策略、记忆、技能和子Agent,得分20.5%。[^1_2]
- **OpenClaw**:ARC Prize官方将通用OpenClaw Harness适配到ARC-AGI-3,允许记忆和代码执行工具,得分5.2%。[^1_2]
- **Human Intelligence Harness**:ARC Prize官方"把最大化人类智能塞进Agent Harness"的对照实验,得分95.3%。[^1_2]
- **Vision - Continual Learning v1**(Vansh):带跨局/跨关卡持续学习权重的多模态Agent,得分63.1%。[^1_2]
- **TELL**(Dots Post-train Team):单一持续对话Agent,把确认过的知识累积写入`MEMORY.md`文件,得分43.9%,这一"持续记事本"思路与VISTA的`GUIDE.md`/`WORKING.md`机制高度相似。[^1_2]

前代ARC-AGI-2上也有相关程序合成路线的延伸,如Symbolica的Agentica REPL Agent框架(Opus 4.6达85.28%),以及Jeremy Berman的进化式测试时计算方法(遗传算法生成Python变换程序)。[^1_10][^1_2]

## 生态定位小结

把这些项目按"是否做程序合成"和"感知模态"两个维度分类最能看清全貌:VISTA与AVO代表**无程序合成+直接感知**一端,追求极简设计和对通用模型视觉/语言能力的直接利用;Tycho、Schema、Retrodict、baseline1等代表**程序合成+可执行世界模型**一端,追求可验证、可搜索的因果结构。有趣的是两条路线目前都能在公开集上摸到100% RHAE的天花板,这说明当前ARC-AGI-3公开集本身可能已经接近饱和,真正的分水岭在半私有/私有测试集上的泛化能力,这也是VISTA原文特别强调"private set才是真正的泛化考验"的原因。对于三国杀等你自己在做的卡牌智能体项目,Schema的"状态落地+机制发现联合建模"和VISTA的"无损视觉记忆+自由语言推理"两种设计模式都值得直接借鉴到Agent Harness架构里。[^1_1]

<span style="display:none">[^1_11][^1_12][^1_13][^1_14][^1_15][^1_16]</span>

<div align="center">⁂</div>

[^1_1]: https://vista-research.github.io/

[^1_2]: https://arcprize.org/leaderboard/community

[^1_3]: https://arxiv.org/html/2607.28287v1

[^1_4]: https://schema-harness.github.io/

[^1_5]: https://developer.nvidia.com/blog/nvidia-avo-reaches-100-on-arc-agi-3-demonstrating-a-frontier-level-general-purpose-architecture-for-long-horizon-autonomous-agents/

[^1_6]: https://github.com/LeePresswood/Claude-Plays-Pokemon

[^1_7]: https://ai-radar.merimerimeri.com/episodes/564-how-claude-3-7-plays-pokemon/

[^1_8]: https://www.lesswrong.com/posts/sehJYg5Yny9fvpbpt/a-year-late-claude-finally-beats-pokemon

[^1_9]: https://www.vortak.net/posts/claude-fable-5-beats-pokmon-firered-only-using-vision

[^1_10]: https://www.symbolica.ai/blog/arcgentica

[^1_11]: https://github.com/QingzeHu/pokemon-vision-agent

[^1_12]: https://www.mindstudio.ai/blog/what-is-arc-agi-3-interactive-benchmark

[^1_13]: https://benchlm.ai/benchmarks/arcagi3

[^1_14]: https://news.ycombinator.com/item?id=47538078

[^1_15]: https://mrpeppersdev.github.io/agent-infrastructure-landscape/systems/claude-plays-pokemon-anthropic--twitch-tv

[^1_16]: https://deniseholt.substack.com/p/arc-agi-3-we-didnt-expect-this-to


---

# VISTA项目与Tycho项目在架构设计上的核心差异有哪些

VISTA 与 Tycho 的根本差异，不在于是否都能在 ARC-AGI-3 上拿到 100 RHAE，而在于它们选择了两种不同的“世界理解接口”。\*\*VISTA 让多模态模型直接看世界、用自然语言形成可修正的模糊理解；Tycho 则让编码智能体把世界写成可执行、可验证、可搜索的 Python 世界模型。\*\*两者分别代表 *perception-first / language-native harness* 与 *model-based / programmatic harness* 两端。[^2_1][^2_2]

## 架构总览

| 维度 | VISTA | Tycho |
| :-- | :-- | :-- |
| 核心范式 | 直接交互式视觉推理 | 主动抽象（active abstraction）+ 可执行世界模型 |
| 中间表示 | 自由文本推理、`GUIDE.md`、`WORKING.md`、原始视觉历史 | 游戏特定 Python 程序：状态、转移、渲染、终局条件 |
| 对世界模型的态度 | 允许模型在语言中保有“模糊但够用”的心智模型 | 将显式、可执行、可检验的世界模型作为关键工具，但按需使用 |
| 感知输入 | 原始 512×512 PNG，支持局部放大、像素读取 | 官方 64×64 色彩栅格及结构化事件/元数据，Python 可查询历史 |
| 记忆设计 | 全量、无损、按帧/区域/像素可回看的视觉记忆 | 可查询的结构化历史、持久工作区、跨关卡程序/笔记/计划 |
| 预测/验证 | 行动前用语言写出预期，行动后对照可见变化 | 执行 `transition` 和 `render` 预测，回放历史轨迹并验证 |
| 规划方式 | 在语言中基于当前感知、笔记和视觉回看进行隐式规划 | 可在模拟器中对未来动作序列进行显式搜索与规划 |
| 角色划分 | 单个通用多模态 Agent 的极简闭环 | Actor + 可选 Builder，强调“何时建模/修复/绕过模型”的元推理 |
| 系统哲学 | 尽量不约束模型的原生多模态理解能力 | 将抽象显性化、可审计化、可反证化、可模拟化 |

VISTA 的官方表述可以浓缩为三件事：**高维视觉感知、自由语言推理、无损视觉记忆**。Tycho 则由四类组件构成：**结构化证据记录、可执行假设程序、验证与规划、对模型使用时机的元推理策略**。[^2_2][^2_1]

## 世界模型表示

### VISTA：模型脑中的“语言世界模型”

VISTA 不要求 Agent 把环境压缩为一个满足固定接口的符号系统。它会给模型当前 PNG 图像、可用动作、历史视觉帧与两类笔记空间：

- `GUIDE.md`：跨关卡可复用的机制理解，例如物体角色、局部物理、操作规则
- `WORKING.md`：当前关卡的临时草稿、假设、局部坐标关系、待验证计划
- `inspect`：重新查看任意历史帧、动画中间帧或局部区域
- `read_pixels`：从指定历史图像区域读取精确颜色值
- `play`：执行环境动作

VISTA 要求 Agent 在执行动作前说明“预计会发生什么”，行动后记录“哪些变化符合或违背预期”，但这个预期仍然是自然语言描述，而不是必须执行成功的状态转移函数。它把抽象的自由度交给基础 VLM：Agent 可以按视觉概念、几何关系、对象功能、策略直觉，甚至临时命名的概念进行推理。[^2_1]

例如，对于跳棋式的规则，VISTA 可以只留下“绿色棋子可跨过相邻棋子跳到空洞；紫色基座可作为永久跳板；红色件可移动但不被移除”等一页文字化规则。官方对比指出，等价的程序系统可能需要数千行代码才能表达坐标、对象、合法性、状态更新及规划细节。[^2_1]

这意味着 VISTA 的“世界模型”是：

$$
M_{\text{VISTA}} \approx \{\text{视觉历史},\ \text{语言假设},\ \text{持久笔记},\ \text{VLM 隐状态}\}
$$

它是**可修订的、非形式化的、部分隐式的**，优势在于表达成本低、适合高维感知与语义不确定性。

### Tycho：工作区中的“可运行世界模型”

Tycho 则把世界假设外化为可编辑 Python 代码。一个 Tycho 世界模型必须实现四个接口：

```python
def init_state(initial_grid, level_index):
    ...

def transition(state, action):
    ...

def render(state):
    ...

def outcome(state):
    ...
```

其语义分别是：

- `init_state`：将该关卡初始观测映射到内部状态；
- `transition`：执行动作并推进状态；
- `render`：从内部状态生成预测的网格观测；
- `outcome`：判断当前是进行中、关卡完成还是失败。

此外，模型还可以提供搜索所需的候选动作、状态哈希、子目标、启发式函数、自定义 planner，以及为显示量化不确定性保留的 `observation_variants`。Tycho 不预设固定的对象本体：状态可以是原始格子、对象列表、UI 模式、计数器、工具选择、有限状态机、几何约束或它们的组合。[^2_2]

可以将 Tycho 的世界模型写成：

$$
\hat{M}_{\text{Tycho}}
=
(\hat{s}_0,\ \hat{\delta},\ \hat{\rho},\ \hat{\omega})
$$

其中：

- $\hat{s}_0$：关卡初始内部状态；
- $\hat{\delta}$：动作条件下的状态转移；
- $\hat{\rho}$：状态到视觉网格的渲染；
- $\hat{\omega}$：终局状态分类。

因此，Tycho 不只是“知道一个规律”，而是要能执行：

$$
\hat{s}_{t+1} = \hat{\delta}(\hat{s}_t, a_t), \qquad
\hat{o}_{t+1} = \hat{\rho}(\hat{s}_{t+1})
$$

并将预测结果与真实环境返回的下一帧比较。[^2_2]

## 感知与记忆

### VISTA：视觉保真优先

VISTA 的输入是原生视觉形式：实验中接收 512×512 PNG，即官方 64×64 画面经 8 倍最近邻放大并带网格线的版本。模型并不会被明确告知底层是 64×64 的离散格子；它需要通过视觉自行理解对象、空间布局、格点结构和局部变化。系统还验证了相同机制在文本化 1D 网格、二维图像和三维渲染中都能工作。[^2_1]

VISTA 最有特色的模块是**无损视觉记忆**：

- 每个环境返回帧都完整保存，包括中间动画；
- 每帧有回合和帧编号；
- Agent 可以随时选择历史任一帧重新看；
- Agent 可以放大某个视觉区域；
- Agent 可以对细粒度颜色/像素进行精确读取；
- 历史帧的检索是 Agent 自主决定的显式注意力，而非仅依赖上下文窗口里的隐式 KV attention。

这对视觉 Agent 特别关键。传统上下文压缩往往会保留“某个门变蓝了”的文字摘要，却丢失门的精确坐标、形状、边界、动画时序、邻接关系或局部像素变化。VISTA 的策略是**不强制过早压缩**，让模型在新证据出现后再回看原始视觉证据。[^2_1]

### Tycho：证据结构化优先

Tycho 同样会持久保存历史，但其主目标不是让 VLM 无损“再看一眼”，而是为验证与程序化推理提供一条可信证据链。它将交互史组织为带类型的记录，包括：

- 可采取动作的决策帧；
- Agent 选择的动作及其动作成本；
- 动作后的中间动画帧；
- 成功终局帧；
- 失败终局帧；
- reset 产生的初始化状态；
- 关卡切换及进度事件；
- 每一步对应的动作掩码和结果标签。

Tycho 特别强调不能混淆决策帧、动画帧和终局帧：Agent 只能在决策帧上选择动作，因此验证器不能把动画或终局画面错误当作一个新的可行动状态。其工作区按关卡、回合保存 PNG/TXT/JSON；Actor 或 Builder 可通过 `wmlib` 从 Python 中查询历史转移、终局、reset 尝试与动画关键帧。[^2_2]

换句话说：

- VISTA 的记忆问题是：**“我还能以原始视觉精度重新审视什么？”**
- Tycho 的记忆问题是：**“什么证据可以构成、反驳或验证一个可运行的因果假设？”**


## 验证、反事实与规划

### VISTA：预期驱动的软验证

VISTA 的验证机制是行为上的，而不是形式上的：

1. 从当前视觉观察形成假设；
2. 以语言写下对下一步视觉结果的预期；
3. 执行动作；
4. 比对实际可见变化和预期；
5. 在笔记中修正理解；
6. 必要时回看历史帧，检查早期假设遗漏的细节。

优点是其验证范围天然适配视觉和语义复杂性：模型不必在早期就写出完整动力学，也不必解释每一个像素。缺点是它无法像程序模型那样系统地枚举未来状态，亦无法给出严格的“该假设覆盖了哪些历史转移、预测了多少像素”的机器可检验指标。[^2_1]

### Tycho：硬验证与模拟规划

Tycho 的验证流程更接近可证伪的系统辨识：

1. 从交互证据构建或修订 Python 世界模型；
2. 从历史初始状态按真实动作序列执行 `transition`；
3. 调用 `render` 预测对应观测；
4. 比对预测观测与真实历史；
5. 比较预测的终局判断与真实关卡完成/失败事件；
6. 如果预测不一致，修复模型、放弃模型，或直接绕过模型采取行动；
7. 若模型通过足够的历史验证，则在模型内搜索未来动作序列；
8. 执行现实动作并以新观测继续反证或更新模型。

Tycho 允许 `render` 对确实尚未确定的像素输出 $\bot$，即“我不对这个位置作预测”。这让验证区分“局部无知”与“做出了错误预测”：模型可只覆盖自己能可靠建模的部分，同时对已声称可预测的像素承担可检验责任。[^2_2]

规划上，Tycho 可在真实动作之前进行模拟：

$$
\hat{s}_{t+k}
=
\hat{\delta}(
\ldots \hat{\delta}(\hat{s}_t, a_t),
\ldots,
a_{t+k-1})
$$

若搜索得到可完成关卡的动作序列，Agent 可将其作为现实执行方案。真实环境的一次动作只会消耗一次计分动作，但模型内部模拟可以运行大量步，因此对长程、可组合、确定性较高的机制尤为有利。[^2_2]

## 控制流与角色分工

VISTA 的控制回路非常扁平：

```text
视觉状态 + 可用动作
        ↓
单个 VLM 进行语言推理
        ↓
可选：查看历史图像 / 局部放大 / 读像素 / 更新笔记
        ↓
说明预测
        ↓
play(action)
        ↓
保存新视觉帧并继续
```

它的关键主张是：只要做好视觉访问与长期记忆，强通用 VLM 本身已具备足够的推理能力，不需要把认知强行分拆为对象解析器、规则合成器、验证器、planner 等工程流水线。VISTA 是一种**尽可能薄的 agent harness**。[^2_1]

Tycho 的控制回路则是可切换的元控制系统：

```text
结构化证据历史 + 当前决策帧
        ↓
Actor 判断：直接行动，还是建立/使用/修复模型？
        ├── 直接推理 → take_action
        └── 委派 Builder
                 ↓
          生成或修订 Python 世界模型
                 ↓
         历史回放验证 / 预测覆盖检查
                 ↓
          规划、提出探测动作或候选计划
                 ↓
           Actor 最终决定 take_action
```

Tycho 论文并没有假设“始终建模”最优，反而将**何时值得建模**视为研究对象。它比较了四种模型维护策略：


| 策略 | 做法 |
| :-- | :-- |
| No world model | Actor 纯粹依据观测和历史直接决策 |
| Single | 同一个 Actor 同时负责行动和建模 |
| Orchestrator | Actor 在判断有价值时委派 Builder 建模或修复 |
| Trigger | 系统在验证失败时自动触发 Builder 修复 |

论文报告中，Actor 按需委派 Builder 的 **Orchestrator** 策略效果最好；这说明“模型是否需要维护、何时维护、维护到什么程度”并不只是实现细节，而是决策资源分配问题。[^2_2]

## 对你的工程启示

如果将这两套设计迁移到多模态 RAG、GUI Agent、视频理解或你关心的卡牌游戏 Agent，它们不是非此即彼，较合理的生产架构通常是**VISTA 做前台感知与灵活理解，Tycho 做高价值机制的局部可执行化**。

### 更适合 VISTA 的场景

- 视觉输入高维且对象本体难以预定义，例如复杂 UI、视频、3D 场景、游戏截图；
- 环境变化多样、规则含糊、机制难以快速编程；
- 任务更依赖空间直觉、语义理解、视觉相似性或异常发现；
- 需要最小系统复杂度，快速评估底座 VLM 是否已足够强；
- 需要保留原始证据以便人工审计、重放，或在后续假设改变后重新解释旧观测。

对于视频 RAG / VLM Agent，可以直接借鉴：将关键帧、局部 crop、OCR 图层、轨迹片段保留为可寻址的无损或近无损 memory asset，而不是只塞进摘要。Agent 先从语义摘要定位，再根据不确定性回看原始片段。

### 更适合 Tycho 的场景

- 环境可近似为离散、低随机性、可重复执行的状态机；
- 真实试错成本高，必须尽量在内部仿真而非线上环境中试错；
- 任务包含明确的长程规划、组合动作、资源约束、可达性搜索；
- 需要对 Agent 的认知过程做单元测试、回归测试、故障定位和审计；
- 机制一旦识别可以跨多个关卡、局面、用户会话或业务流程复用。

例如三国杀 Agent 若只做截图或局部状态理解，VISTA 风格的视觉记忆和自由语言策略归纳很有价值；但当你已经能稳定抽取卡牌、角色、血量、技能、阶段、弃牌堆等结构化状态后，Tycho 式局部世界模型会更实用：

```python
state = {
    "phase": "play",
    "self_hand": [...],
    "public_board": {...},
    "hp": {...},
    "skills": {...},
    "known_constraints": {...},
}

def transition(state, action):
    # 技能、响应窗口、伤害结算、距离、手牌和弃牌变化
    ...

def outcome(state):
    # 回合目标、局部胜率估计、残局终局或策略约束违反
    ...
```

此时可执行模型不必覆盖整套规则引擎。更现实的做法是只建模当前决策需要的部分，例如“本回合可行的伤害链”“响应窗口”“资源消耗”“敌我收益变化”，未知技能或隐手牌则以不确定分支、抽象状态或模型 abstention 处理。这也正符合 Tycho 对**决策相关建模**而非强求完整复原的设计。[^2_2]

## 可组合的混合架构

我认为最值得实现的是一个 **VISTA × Tycho hybrid harness**，可概括为：

$$
\text{Raw Multimodal Evidence}
\rightarrow
\text{VISTA-style Lossless Memory}
\rightarrow
\text{Language Hypothesis}
\rightarrow
\text{Tycho-style Partial Program Model}
\rightarrow
\text{Verified Planning / Action}
$$

具体可以分为五层：

1. **原始证据层**\
保存截图、视频段、音频段、OCR、UI tree、操作轨迹、服务日志。每个观测具备时间戳、动作前后关系、来源与哈希，支持局部重看与回放。
2. **VLM 理解层**\
让 VLM 做对象发现、异常解释、规则描述、歧义归因、跨模态关联。产物是自由文本假设、候选状态 schema、要验证的预测。
3. **世界模型触发器**\
不是每次都合成程序。仅在满足以下任一信号时触发：
    - 预期后续动作超过阈值；
    - 单次现实试错成本高；
    - 发现高复用机制；
    - 语言假设相互冲突；
    - 连续预测失败；
    - 需要枚举或搜索大量候选动作。
4. **局部可执行模型层**\
为关键机制生成小型、可回放、可单测的 Python/DSL 模块。要求具备最小 `init_state / transition / render-or-observe / outcome` 接口，但允许不确定性和局部覆盖。
5. **验证与策略层**\
以历史 replay、性质测试、反事实模拟、动作队列失效机制控制执行。若模型与新观察冲突，先使计划失效，再决定修复模型、降级为直接 VLM 推理，或进行信息增益最大的探测动作。

这一组合避免了 VISTA 单独使用时“难以严密搜索和验证”的弱点，也避免了 Tycho 单独使用时“过早结构化、程序化负担高、对高维视觉细节压缩过强”的弱点。VISTA 表示层负责**不丢证据**，Tycho 模型层负责**只在值得时把证据变成可证伪、可规划的机制**。[^2_1][^2_2]

## 结论

一句话归纳：

- **VISTA** 的问题意识是：*怎样让基础 VLM 在未知世界中保持足够长、足够细的感知与记忆，以自然语言直接学会行动？*
- **Tycho** 的问题意识是：*怎样让 Agent 主动把有限交互经验变成可执行的因果模型，并决定何时值得为此付出建模成本？*

前者是“**让模型像人一样观察、回忆、描述和行动**”；后者是“**让模型像科学家/程序员一样提出可运行理论、用过去实验反证它、再在理论中预测未来**”。两者在 ARC-AGI-3 公共集上都达到满分，但其可迁移的工程资产截然不同：VISTA 更适合构建强感知、多模态、低约束的通用 Agent 基座；Tycho 更适合构建可验证、可搜索、可回归测试的高可靠决策系统。[^2_1][^2_2]

<span style="display:none">[^2_10][^2_11][^2_12][^2_13][^2_14][^2_15][^2_16][^2_3][^2_4][^2_5][^2_6][^2_7][^2_8][^2_9]</span>

<div align="center">⁂</div>

[^2_1]: https://vista-research.github.io/

[^2_2]: https://arxiv.org/html/2607.28287v1

[^2_3]: https://arxiv.org/abs/2607.28287

[^2_4]: https://arxiv.org/pdf/2511.10182.pdf

[^2_5]: https://github.com/NIMI-research/Tycho/

[^2_6]: https://github.com/AkihikoWatanabe/paper_notes/issues/6291

[^2_7]: https://arcprize.org/arc-agi/3

[^2_8]: https://www.themoonlight.io/en/review/tycho-active-abstraction-with-programmatic-world-models-for-arc-agi-3

[^2_9]: https://blog.tib.eu/2026/07/31/from-the-arc-agi-3-challenge-towards-agentic-ai-for-science/

[^2_10]: https://www.techtimes.com/articles/322506/20260731/arc-agi-3-gets-open-source-agent-that-writes-python-world-models-instead-neural-weights.htm

[^2_11]: https://digg.com/tech/ey3apt71

[^2_12]: https://x.com/bengoertzel/article/2053072200987545755

[^2_13]: https://www.alphaxiv.org/abs/2605.26144

[^2_14]: https://runtimewire.com/article/nvidia-avo-arc-agi-3-perfect-public-score

[^2_15]: https://alphasignal.ai/news/nvidia-s-avo-hits-100-on-arc-agi-3-where-the-bare-model-scores-30

[^2_16]: https://developer.nvidia.com/blog/nvidia-avo-reaches-100-on-arc-agi-3-demonstrating-a-frontier-level-general-purpose-architecture-for-long-horizon-autonomous-agents/


---

# VISTA项目的系统架构和核心工作流程是怎样的

VISTA 是一个**极简的视觉交互 Agent Harness**：它不把环境规则强制编译为程序化世界模型，而是给通用多模态模型提供原始视觉输入、可回溯的无损视觉记忆、两个文本笔记空间和少量交互工具，让模型以自由语言建立、检验和修订对未知世界的理解，再逐步行动。其核心闭环是：**Observe → Recall/Inspect → Reason → Predict → Act → Record/Revise**。[^3_1]

## 系统架构

VISTA 把“智能”主要留给底座 VLM，而 Harness 只负责提供高保真感知、可寻址记忆和稳定的互动接口。以 ARC-AGI-3 为例，使用的后端包括 Claude Opus 5.0（Claude Code CLI）或 GPT-5.6 Sol（Codex CLI）；两者都经过同一个短提示词、同一组工具和相同的运行设置。[^3_1]

```text
┌──────────────────────────────────────────────────────────────┐
│                        ARC-AGI-3 环境                         │
│  当前世界状态 ── 游戏动作 ──> 新状态 / 动画帧 / 关卡进度         │
└───────────────┬──────────────────────────────────────────────┘
                │
                │ 当前画面、动画序列、可用动作、状态/进度
                ▼
┌──────────────────────────────────────────────────────────────┐
│                    VISTA Harness（薄编排层）                  │
│                                                              │
│  1. Visual Observation                                      │
│     - 当前原始 PNG 图像                                      │
│     - 可选局部放大                                           │
│     - 可选精确像素/颜色读取                                  │
│                                                              │
│  2. Lossless Visual Memory                                  │
│     - 存储环境返回的每一帧                                   │
│     - turn/frame 索引                                        │
│     - 历史帧、动画帧、局部区域可随时 inspect                  │
│                                                              │
│  3. Externalized Text Memory                                 │
│     - GUIDE.md：跨关卡持久规则/概念/机制                      │
│     - WORKING.md：当前关卡假设、坐标、计划和草稿               │
│                                                              │
│  4. Tool Interface                                           │
│     - inspect(...)                                           │
│     - read_pixels(...)                                       │
│     - 读写 GUIDE.md / WORKING.md                              │
│     - play(action)                                           │
└───────────────┬──────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│                  通用多模态模型（主决策体）                   │
│  当前视觉 + 被检索历史 + 文本笔记 + 动作集合                   │
│                                                              │
│  自由语言理解、形成假设、规划、预期下一帧、选动作、更新笔记       │
└──────────────────────────────────────────────────────────────┘
```

VISTA 的工程重点不在专用视觉解析器、对象追踪器、规则合成器、搜索器或程序验证器，而是最大限度保留模型的原生多模态能力。官方将其总结为三块：**自然高维视觉感知、自由语言推理、无损视觉记忆**。[^3_1]

## 核心模块

| 模块 | 输入/状态 | 主要职责 | 为什么重要 |
| :-- | :-- | :-- | :-- |
| 视觉感知 | 当前环境渲染画面 | 把原始视觉状态交给 VLM 观察对象、空间关系、局部变化、UI 状态 | 不预先把世界压扁为人工定义的对象 schema |
| 视觉记忆 | 历史全部帧、动画中间帧、turn/frame 索引 | 支持按时间、区域和像素级别回看旧证据 | 避免上下文截断或文字摘要导致视觉细节永久丢失 |
| `inspect` | 指定历史帧或矩形区域 | 恢复全分辨率历史视觉证据；可一次取多个画面比较 | 让 Agent 主动选择“何时、回看哪里” |
| `read_pixels` | 指定帧和局部区域 | 返回精确颜色采样 | 对离散格、微小对象、局部差异做细粒度确认 |
| `GUIDE.md` | 跨关卡稳定知识 | 存放对象角色、规则、目标猜测、可复用策略 | 将机制学习从前一关迁移到后一关 |
| `WORKING.md` | 当前关卡临时状态 | 记录局部坐标、当前计划、实验结果、未确认假设 | 避免污染跨关卡的稳定知识 |
| 自由语言推理 | 视觉、历史、笔记、动作 | 生成可修正的“模糊世界模型”、规划和动作决策 | 不要求先构造完整的可执行动力学 |
| `play(action)` | 候选环境动作 | 触发真实环境交互，得到新帧或动画序列 | 新观测为假设提供支持或反证 |
| 上下文续接 | 上下文接近上限时 | 写入简洁 continuation state，刷新模型上下文但保留外部记忆 | 将超长任务状态从模型上下文迁移到外部可检索资产 |

在实验中，VISTA 接收的是 512×512 的 PNG：来自官方 64×64 格子的 8 倍最近邻放大图，并插入网格线。模型**不会被显式告知**底层是一个 64×64 网格；它需要凭图像自主发现格点、对象、几何关系和规则。模型也可请求任意矩形区域的放大视图。[^3_1]

## 每步工作流

一次典型的决策回合可以拆为以下八步：

```text
环境当前帧
  ↓
1. Observe：看到当前视觉状态、可用动作、进度/状态
  ↓
2. Recall（按需）：回看历史帧、动画帧或指定区域
  ↓
3. Inspect（按需）：局部放大或读取精确像素
  ↓
4. Reason：以自然语言归纳对象作用、机制、目标、约束
  ↓
5. Update Memory：写 GUIDE.md 或 WORKING.md，保留/修订假设
  ↓
6. Predict：在真实动作前，明确写出“预期会看到什么”
  ↓
7. Act：调用 play(action)
  ↓
8. Compare & Revise：记录可见变化；将实际结果与预测比对，
   更新规则理解、计划和笔记，然后进入下一轮
```

VISTA 提示词的关键约束非常短，但对流程影响很大：

> “完成游戏时尽量少用游戏动作；构建并使用紧凑、可修订的游戏及当前状态模型；每次 `play` 前简述预期看到的结果，之后说明所有可见变化；把持久规则记在 `GUIDE.md`，当前关卡草稿可放在 `WORKING.md`。”[^3_1]

因此，**预测—观察对照**是 VISTA 的核心“软验证机制”：

$$
\text{hypothesis}_t
\rightarrow
\text{predicted visual outcome}_{t+1}
\rightarrow
\text{real action}
\rightarrow
\text{observed outcome}_{t+1}
\rightarrow
\text{revise hypothesis}_{t+1}
$$

它没有要求预测必须是可运行程序，也不要求每一步完整地还原世界状态。只要语言模型能表达一个“足够支持下一步”的可修正理解，便可继续行动。[^3_1]

## 无损记忆流程

VISTA 与普通“长上下文 Agent”最关键的差异，是把视觉历史保存为**外部、显式、无损且可查询的记忆库**，而不是仅依赖模型 KV cache 或文字摘要。

```text
play(action)
    ↓
环境返回：
- 最终状态帧
- 可能包含若干中间动画帧
- 游戏状态 / 关卡进度
    ↓
VISTA 逐帧落库：
(frame_id, turn_id, image, action_context, status)
    ↓
当前最终帧 → 下一轮的默认观察
历史所有帧 → 可被 inspect / read_pixels 重新取回
```

这个设计处理的是交互式视觉任务中常见的“事后发现旧细节重要”问题。例如：

- 第 20 步发现某种颜色可能代表“不可移动障碍”；
- Agent 可以回看第 2 步和第 8 步的原图；
- 比较该颜色在不同交互后是否变化；
- 读取特定局部像素，确认它到底是边框、物体、阴影还是动画残影；
- 再反向修订之前记录在 `GUIDE.md` 中的规则。

VISTA 认为，与其让系统在每一步主动做大量摘要和结构化，不如保留完整观察并延迟解释：\*\*先把证据存住，需要时由模型主动检索。\*\*官方将这种自选帧、自选区域、自选像素的机制称为显式注意力（explicit attention）。[^3_1]

## 跨关卡工作流

ARC-AGI-3 的一个游戏由多个关卡组成：关卡之间会变换布局、对象或约束，但通常共享底层机制。因此 VISTA 并非“每一关从零开始”的单回合 Agent，而是一个在同一游戏内持续学习的 Agent。

```text
Level 1：低风险探索
  ├─ 测试对象可否移动
  ├─ 尝试动作并观察局部因果
  ├─ 初步判断游戏目标
  └─ 将稳定规律写入 GUIDE.md
          ↓
Level 2：机制迁移
  ├─ 读取 GUIDE.md
  ├─ 识别已知对象/规则的新布局
  ├─ 只测试新增约束或边界条件
  └─ 修订 GUIDE.md
          ↓
Level N：更高效的规划与执行
  ├─ 基于稳定规则减少探索动作
  ├─ 主要更新 WORKING.md 中的局部方案
  └─ 若遇反例，再回退并修订全局理解
```

其中：

- `GUIDE.md` 应只保存可跨层复用、较稳定、经过多次支持的机制；
- `WORKING.md` 记录当前层局部布局、候选路线、未确认推测、暂时坐标；
- 当一个原有规则被反例推翻时，Agent 应该修订而不是盲目累积相互冲突的笔记；
- 回看视觉 memory 能让 Agent 判断“规则真的错了”，还是自己先前忽略了某个视觉条件。[^3_1]

这相当于在一个游戏实例里形成了两层记忆：

$$
M = M_{\text{global-guide}} \cup M_{\text{level-working}} \cup M_{\text{lossless-visual}}
$$

其中 `GUIDE.md` 偏向规则知识，`WORKING.md` 偏向短期任务状态，而视觉记忆保留一切尚未被文本抽象覆盖或可能被误解的原始证据。

## 与程序化 Agent 的边界

VISTA 的架构有意避开 Tycho、Schema、Retrodict 等系统的主路线。后者通常将交互轨迹写成可执行的状态表示、转移函数和目标条件，并通过历史回放与模拟搜索验证它们；VISTA 则把“世界模型”保持为自由语言笔记、视觉证据及底座模型内部表征的组合。[^3_1]

以官方展示的跳跃规则为例：

- **程序化世界模型**需要写明棋盘坐标、物体集合、合法动作判定、跳跃路径、被跳对象移除/保留、状态更新及目标判断；VISTA 页面举例称某一游戏的完整世界模型约有 4,000 行 Python。
- **VISTA 的自由语言世界模型**只需用一页 `GUIDE.md` 记录类似“绿色钉可沿正交方向跨相邻钉跳至两格外空洞；跨越绿色钉会移除它；紫色固定件可作为不会被移除的跳板；红色件可移动且保留”等规则。它不可执行，但在当前任务中足以帮助模型规划下一步。[^3_1]

因此，VISTA 的系统逻辑不是：

$$
\text{Observation}
\rightarrow
\text{Program Synthesis}
\rightarrow
\text{Simulator Search}
\rightarrow
\text{Action}
$$

而是：

$$
\text{Raw Visual Evidence}
\rightarrow
\text{Free-form Hypothesis}
\rightarrow
\text{Expected Visible Result}
\rightarrow
\text{Real Interaction}
\rightarrow
\text{Revision}
$$

其优点是架构很薄，对高维或语义复杂的视觉场景更自然；代价是没有显式模拟器，也缺少由程序回放、穷举搜索和形式化一致性检查带来的可验证性。[^3_1]

## 性能与工程含义

以 Claude Opus 5.0 为底座时，VISTA 在 ARC-AGI-3 的 25 个公开游戏、183 个关卡中全部完成，平均 RHAE 为 100.00，共进行了 7,542 次环境动作；据项目页面统计，这比首次游玩的人类参考动作数少 56.0%。以 GPT-5.6 Sol 为底座时也完成全部 183 关，平均 RHAE 为 98.27。只有 `play` 这类真实环境动作计入评分，内部思考、查看历史帧、局部放大和读像素不计入环境动作成本。[^3_1]

对你更关注的多模态 RAG / Video Agent / GUI Agent 场景，VISTA 可直接抽象为以下工程范式：

```text
原始多模态证据
  ├─ 视频关键帧、原始片段、音频、OCR、UI 截图、DOM/日志
  ↓
可寻址无损证据库
  ├─ 时间、区域、轨迹、来源、事件索引
  ↓
VLM 自由语言理解
  ├─ 可修订假设、策略、因果解释
  ↓
双层外部笔记
  ├─ GUIDE：稳定领域知识、操作机制、用户偏好
  └─ WORKING：当前任务证据、待验证点、执行计划
  ↓
预测驱动工具调用
  ├─ 调用前声明预期
  └─ 调用后比较结果，触发修订或继续执行
```

真正值得复用的并非 ARC-AGI-3 的图像格式，而是四条系统原则：

- **保留原始证据**：摘要和结构化抽取只是索引/加速层，不能成为唯一事实来源。
- **记忆可寻址**：支持按时刻、区域、对象、轨迹和证据来源精确回看。
- **世界模型可修订**：将机制理解写入可版本化外部状态，而非仅留在上下文或模型隐状态中。
- **把预测纳入执行契约**：每次高风险工具调用前记录预期；调用后自动对账、评估偏差、修正策略。

VISTA 也明确承认，公开 ARC-AGI-3 游戏是否已经出现在新模型训练数据中无法排除，私有集才是严格泛化能力的更重要检验。因此，它更适合作为一种很有价值的 Agent 系统设计模式，而不是单凭公开集满分就断言其已经证明了通用物理世界理解能力。[^3_1]

<div align="center">⁂</div>

[^3_1]: https://vista-research.github.io/


---

# 对这些相关的进行头脑风暴，针对现在市场上所有的相关的工作有什么现实落地的先进性、可能性、创新性以及优越性，要求全面等

把 VISTA / Tycho / Schema / AVO / Claude Plays Pokémon 这一批 ARC-AGI-3 系交互式 Agent Harness 放到当前企业级 Agent 市场里看，它们代表的不是又一个跑分刷榜的研究项目，而是**下一代 Agent 记忆与世界建模层的原型**——而这恰好是当前市场最大的短板：Gartner 数据显示 2026 年已有 80% 的企业应用嵌入了某种 Agent，但真正投产的只有 31%，88% 的 pilot 从未上线，核心卡点集中在长程记忆、可验证性和治理三件事上，而不是模型智能本身。[^4_1][^4_2]

## 市场现状：卡在哪里

先明确"竞品"到底是谁。市场上现有的落地方案大致分三类，都存在明显缺口：


| 类别 | 代表产品 | 核心短板 |
| :-- | :-- | :-- |
| 商业 Computer-Use Agent | Claude Computer Use、Gemini Project Mariner、OpenAI ChatGPT agent | 依赖 DOM/accessibility tree 为主，纯视觉仅作 fallback；缺乏跨任务持久世界模型，每次会话近乎"失忆" [^4_3] |
| Agent Memory 中间件 | Mem0、向量数据库类记忆栈 | 覆盖 21 个框架、20 种向量库，但本质仍是"语义摘要+检索"，会丢失原始高保真证据，且缺少可执行世界模型 [^4_4] |
| 企业 Agent 治理平台 | Gemini Enterprise Agent Platform、Harness.io CI/CD for Agents | 治理、审计、灰度发布做得扎实，但对"Agent到底如何理解和验证它所处的环境"基本不涉及 [^4_5][^4_6] |

这意味着 VISTA/Tycho 这条研究线切入的正是市场的**认知层空白**：不是"Agent 敢不敢做"，而是"Agent 到底能不能可靠理解一个陌生、动态、高维的环境并长期记住"。

## 现实落地的先进性

### VISTA：把"无损视觉记忆"变成可复制的工程组件

VISTA 最大的现实价值不是 ARC-AGI-3 跑满分，而是证明了一个此前被低估的架构选择：**不要在证据进入长期记忆前过早压缩它**。当前几乎所有生产级 Agent Memory 方案（包括 Mem0 一类）默认做法都是把观测转成语义摘要或向量嵌入后再存储，这在语义漂移、细粒度视觉差异（比如 UI 上一个像素级状态变化、视频里一个瞬时表情）场景下会永久丢失关键证据 。VISTA 的"存原始帧+按需 inspect/read_pixels 精确回看"模式，直接可以移植到：[^4_4]

- **企业知识库/多模态 RAG**：把文档截图、图表、视频关键帧原始存档，检索时先用摘要定位候选证据，再按需拉取原始高分辨率片段做二次确认，避免"摘要幻觉"导致的错误引用。
- **GUI Agent 长任务**：当前 Computer-Use Agent 在长会话中普遍依赖压缩过的历史文本记录，VISTA式的无损帧记忆能显著降低"因早期截图信息丢失导致的重复试错"，这正是当前 GUI Agent 桌面/移动场景成功率远低于 Web 场景（Web 高达 87%，移动端普遍 60-70% 徘徊）的重要原因之一 。[^4_3]
- **视频监控/工业质检**：这类场景天然需要"先粗筛异常时刻，再回放高精度片段核实"，与 VISTA 的 recall→inspect→read_pixels 流程几乎是同构的。


### Tycho/Schema：把"可执行世界模型"做成可审计、可回归测试的资产

企业治理平台目前解决的是"部署流程"是否合规（SSO、审计日志、灰度发布），而不是"Agent 的决策逻辑本身"是否可验证、可回归测试 。Tycho 的核心创新——把交互经验蒸馏为带 `init_state/transition/render/outcome` 接口的可执行程序，并用历史回放做证伪——本质上补上了这一层空白：它让 Agent 的"认知"本身变成像代码一样可以做单元测试、CI 回归、版本管理的工程资产。这对以下场景极具现实意义：[^4_6][^4_7]

- **金融风控/合规 Agent**：任何决策逻辑必须可解释、可追溯、可复现，Tycho 式"用历史数据反证模型"的机制天然契合监管对 AI 决策留痕和可验证性的要求。
- **RPA/流程自动化升级**：传统 RPA 靠硬编码规则、脆弱易碎；纯 LLM Agent 又缺乏确定性和可测试性。Tycho 提供了中间态——用 LLM 生成规则假设，但强制其可执行、可回放验证，等价于"AI辅助生成+人类可审计的确定性引擎"，这与当前企业强调的"混合架构优于纯AI方案"的共识高度一致 。[^4_3]
- **游戏/卡牌AI（你自己的三国杀项目）**：可将确定性强的子机制（伤害结算、距离判定、响应窗口）编译为可执行局部模型，用真实对局历史做反证测试，剩余不确定部分（隐藏手牌、对手心理博弈）留给VLM做语言层策略推理——这正是Tycho论文本身验证过的"按需建模"策略优于"全量建模"或"完全不建模" 。[^4_8]


### AVO：证明了"Harness 而不是模型"才是当前的杠杆点

NVIDIA AVO 把最初为 GPU kernel 优化设计的通用长程 Agent 架构直接迁移到 ARC-AGI-3，仅用相同 Claude Opus 5 就把裸模型 30.2% 的得分拉到 100%，动作效率还比 VISTA 高 12% 。这个结果对企业决策者的现实意义极大：**在给定预算下，投资 Harness 工程比等待下一代模型更快见效**。这与 2026 年行业共识"三大厂商同时把 Harness（治理、路由、控制层）当作独立产品线推出"的趋势完全吻合 ，意味着这类研究已经从"论文demo"进入"厂商级产品竞争"阶段，落地窗口正在收窄，越早布局越有先发优势。[^4_5][^4_9]

## 可能性：能长成什么样的产品

把这些技术组件按成熟度和落地难度排列，我认为存在四层可产品化的机会：

**第一层（可立即原型化，1-2个月）**：无损多模态证据库 + 语义索引的检索增强层。技术上直接复用 VISTA 的"原始帧存档+可寻址回看"思路，接入现有多模态RAG pipeline，作为摘要检索之外的"高保真兜底"模块。风险低，工程量可控。

**第二层（需要中等定制，3-6个月）**：面向特定垂直领域的"预测-验证"执行契约框架。把 VISTA 的"行动前声明预期、行动后对账"模式做成通用中间件，可用于任何高风险工具调用场景（下单、发邮件、改数据库），本质上是给 Agent 装一个自动化的"事前风险声明+事后偏差检测"机制，直接服务于企业对 Agent 可控性的核心焦虑。

**第三层（研究到产品的鸿沟，6-12个月）**：局部可执行世界模型自动生成与验证系统，即 Tycho/Schema 路线的产品化。挑战在于如何让"何时值得建模、何时该直接用LLM"这个元决策稳定、可控、成本可预测，这也是 Tycho 论文自己承认仍在探索的开放问题 。[^4_8]

**第四层（长期，需要生态成熟）**：混合 VISTA+Tycho 架构成为下一代"AI员工"Agent 操作系统的标准组件，即感知层无损存证、决策层按需程序化验证、执行层可回归审计三者统一。这与当前 Gemini Enterprise Agent Platform 把"治理作为默认架构而非附加项"的方向一致 ，但目前没有任何厂商把认知层（世界模型可验证性）和治理层（合规审计）真正打通，这正是最大的空白机会。[^4_5]

## 创新性：这批工作真正新在哪

对比整个市场，我认为三点创新是当前几乎独有的：

**"证据不早熟压缩"的架构主张**。当前几乎所有商业系统（RAG、Agent Memory中间件）都假设"检索前必须先摘要/向量化"，VISTA证明了保留原始高维证据、延迟到检索时才解释，能显著提升长程任务在语义模糊场景下的鲁棒性 。[^4_10][^4_4]

**把"要不要建模"变成可学习的元决策**。Tycho对比No-model/Single/Orchestrator/Trigger四种策略，发现"按需委派建模"显著优于"始终建模"或"从不建模" ，这打破了业界"越结构化越可靠"或"纯LLM推理最灵活"的二元对立框架,为设计混合系统提供了实证依据。[^4_8]

**把 ARC-AGI-3 这种"无规则说明书"的环境当作 Agent 认知能力的通用压力测试**。这比任何单一垂直场景基准更能暴露 Agent 在真实企业场景中最常遇到的问题——面对没有文档、没有API schema、行为随时间/版本变化的遗留系统或第三方黑箱应用时该怎么办，这恰恰是企业IT环境里最常见但业内评测最少覆盖的场景。

## 优越性：相对现有方案好在哪，也要说清局限

优越性不该被神化，需要辩证看：

- 相对纯 DOM/accessibility tree 路线的 GUI Agent，VISTA式纯视觉理解在"非标准布局、canvas UI、图像密集界面"上更具泛化性 ，但计算成本和延迟更高，不适合当前企业首选的"结构化优先、视觉兜底"生产原则。[^4_3]
- 相对向量数据库记忆栈，VISTA/Tycho式的无损存证+可执行验证在可解释性和审计性上明显占优，但存储和检索工程复杂度更高，21框架/20向量库的现成生态短期内不会为这种范式重新洗牌 。[^4_4]
- 相对纯RPA，Tycho式方案更灵活、维护成本更低，但可执行世界模型的自动生成质量目前仍高度依赖底座模型能力和环境确定性，遇到高随机性、对抗性环境（比如真实用户行为、多人博弈类游戏)时验证机制会明显吃力,这也是为什么它在ARC-AGI-3这种规则封闭环境里满分,但迁移到你的三国杀这种有隐藏信息和对手策略博弈的场景时,不能指望简单复用。


## 落地路线图建议

基于以上分析,如果你想把这些idea转成可展示的工程项目,建议按以下优先级推进:

1. 先用VISTA式无损证据库+分层笔记(GUIDE/WORKING)改造你现有的视频RAG或客服知识库系统,验证"延迟压缩"对检索准确率的实际提升,这是成本最低、风险最小的第一步。
2. 再针对三国杀Agent中确定性较强的子机制(伤害结算、距离、响应窗口)做Tycho式局部可执行建模+历史对局回放验证,把这部分从纯prompt工程转成可单测的代码模块。
3. 最后把"预测-验证"执行契约做成一个通用中间件,包在你现有的LangGraph工作流外层,给每个高风险工具调用加上事前声明+事后核对,这个组件几乎可以直接对外做产品化demo,因为它精确命中了当前企业市场"31%投产率、69%卡在治理和可靠性"的最大痛点 。[^4_2][^4_1]

<span style="display:none">[^4_11][^4_12][^4_13][^4_14][^4_15][^4_16][^4_17][^4_18]</span>

<div align="center">⁂</div>

[^4_1]: https://paul-okhrem.com/enterprise-ai-agents-statistics-2026/

[^4_2]: https://www.digitalapplied.com/blog/ai-agent-adoption-2026-enterprise-data-points

[^4_3]: https://zylos.ai/research/2026-02-08-computer-use-gui-agents/

[^4_4]: https://mem0.ai/blog/state-of-ai-agent-memory-2026

[^4_5]: https://tecknoworks.com/ai-this-week-the-harness-arrives/

[^4_6]: https://www.harness.io/blog/ai-deployment-in-production-orchestrate-llms-rag-agents

[^4_7]: https://northflank.com/blog/enterprise-ai-coding-agent-deployment

[^4_8]: https://arxiv.org/html/2607.28287v1

[^4_9]: https://alphasignal.ai/news/nvidia-s-avo-hits-100-on-arc-agi-3-where-the-bare-model-scores-30

[^4_10]: https://vista-research.github.io/

[^4_11]: https://neurips.cc/virtual/2025/137156

[^4_12]: https://dl.acm.org/doi/10.1145/3772318.3790696

[^4_13]: https://arxiv.org/html/2605.29341v1

[^4_14]: https://www.turingpost.com/p/computer-use-ai-agents

[^4_15]: https://worldmm.github.io/

[^4_16]: https://www.linkedin.com/pulse/how-enterprises-building-ai-agents-2026-creativebitsai-ermkf

[^4_17]: https://www.forasoft.com/learn/multimodal-agentic-ai-real-time-systems

[^4_18]: https://fazm.ai/blog/best-open-source-ai-computer-use-agent-2026

