---
story_key: va-5-contract-pieces
baseline_commit: cbba5e9
---

# Story va.5: VISTA 吸收序⑤——契约层三件（矩阵 / 隔离 / 血缘）

**Status:** done

## Story

As a 平台契约层,
I want 清单能力-效果构造期对账、评测器状态结构性隔离、派生观察强制
血缘,
So that 声明与效果不符在构造期即炸（不等到运行期）、模型永远看不到
评分器私有状态、派生证据回链到源。

## 来源

[吸收方案](../vista-absorption-plan-2026-11-16.md) §四 D/E/F——
VISTA ``core/contracts.py``：capability-effect 矩阵构造期强制 /
PublicTask 与 evaluator state 分离（"deliberately absent"）/ derived
必须声明 derived_from、非 derived 不得声明。

## 摸底结论（先查已有能力——避免重造超集）

- 存储层 ``save_derived`` 血缘（Story 2.3 / FR-012）**已有且超集**
  ——F 落在 Observation 信封层（语义派生标记），与存储层互补；
- ToolManifest 字段齐全但**无跨字段一致性校验**——D 为真空；
- VastaLabTask 隐藏规则 docstring 声明「Agent 不可见」但**无结构性
  投影**——E 落差在「约定」而非「构造」。

## Acceptance Criteria:

**Given** ToolManifest 构造
**When** read_only=True 而 risk ∈ {R2,R3,R4}，或 read_only=False 而
risk ∈ {R0,R1}
**Then** 构造期 ValidationError（矩阵：read_only ↔ risk；蓝图 §12.4
语义）；合规形态全通过（存量清单全兼容——R0/R1 全 read_only=True、
R2+ 全 read_only=False，全仓 grep 核验）
**And** VastaLabTask.public_view() 只含 task_id/grid_size/start/goal
——hidden_rule/noise/deviation_injection/seed 结构性缺席（JSON 转储
逐串断言）
**And** Observation(derived=True) 必须带 derived_from、非 derived
不得声明（VISTA 原规则）；纯 Observation() 默认向后兼容

## Tasks/Subtasks

- [x] T1: tool.py——ToolManifest model_validator（risk ↔ read_only
      矩阵，构造期 fail-closed）
- [x] T2: environment.py——Observation 增 derived/derived_from +
      血缘规则 validator（向后兼容默认）
- [x] T3: evaluation.py——VastaLabTask.public_view() 模型可见投影
- [x] T4: 测试 ×10（tests/test_vista_contract_pieces.py）+ 既有测试
      演进 ×1（见下）

## 测试演进（防线前移的诚实簿记）

``test_broken_engine_low_risk_write_denied_read_only_allowed`` 原构造
R0+read_only=False 清单验证 AD-12 降级——该组合被新矩阵构造期拒绝
（防线从运行期前移到声明层）。处置：引擎级改 R2 写工具匹配通用
fail-closed 消息（意图「策略挂→写拒」保留）；「低风险写不放行」
分支（纵深防御，合法清单构造不出）在 test_fallback_pure_function
纯函数层加强断言 basis 消息——语义零丢失，两层各得其所。

## 验证

- **全量 1376 passed / 7 skipped**（核心协议动刀后 1319+ 存量全绿）
- ruff 过；lint-imports 契约 5 kept / 0 broken
- 自测纠错：测试自身 kind="state" 非法字面量改 "decision"；两行凑数
  导入删除（兼容性由全量回归背书）

## 遗留

- Observation derived 标记的写入方（SoM 标注图 / inspect 裁剪图作为
  派生观察上报）→ 随序③ 接线（模型侧协议）落地时启用；
- public_view 目前覆盖 VastaLabTask；CUA 任务集（tasks/）的期望
  answer 同为评测器状态——loop 已只把 task 进 prompt（核验过），
  后续如做任务描述生成器须强制走投影。
