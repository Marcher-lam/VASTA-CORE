---
story_key: va-6-micro-absorptions
baseline_commit: 6641540
---

# Story va.6: VISTA 吸收序⑥——G prompt 纪律 + H 工程小件

**Status:** done

## Story

As a CUA 审计面与存储层,
I want 模型 ex-ante 预期落史可对照、CAS 工件落盘即只读,
So that 「动作前说预期、动作后核验对照」（VISTA prompt 纪律）成为
可审计数据，而非提示词里的软约束；证据文件防事故性篡改。

## 来源

[吸收方案](../vista-absorption-plan-2026-11-16.md) §五 G/H——
VISTA ``prompts/claude.md``（预期先行纪律）与 ``artifacts.py``
（evidence chmod 0o400 + 防篡改校验）。

## 实施面

- **G**：SYSTEM_PROMPT 增可选 ``note`` 字段纪律（输出 schema 不变——
  loop 只读 button/mark/answer，新字段向后兼容）；loop 把 note 落
  history ``model_expect``（**执行前**写入——ex-ante 语义），与
  ``verified``（核验器事后裁决）同条历史前后对照；
  ``history_lines`` 投影渲染「预期:」。
- **H**：CAS 落盘（tmp→replace 后）``chmod 0o400``，
  ``contextlib.suppress(OSError)``（平台不支持时字节校验仍为主
  防线）；幂等重复存走已有 exists→读校验分支，不受只读位影响。

## Acceptance Criteria:

**Given** SYSTEM_PROMPT 与 history 结构
**When** 模型在 JSON 附 note
**Then** history 条目带 model_expect（执行前），history_lines 渲染
「预期:…」；无 note 时投影逐字节不变（存量测试零改动仍绿）
**And** save_artifact 落盘后 blob 权限位为 0o400；重复保存同内容
幂等通过（读校验分支）

## Tasks/Subtasks

- [x] T1: loop.py——SYSTEM_PROMPT 纪律句 + note→model_expect 落史
- [x] T2: revisit.py——history_lines 渲染 model_expect（缺省不渲染）
- [x] T3: sqlite_store.py——CAS 只读位（suppress OSError）
- [x] T4: 测试 ×5（tests/test_cua_micro_absorptions.py）+ 篡改模拟
      测试演进 ×5（见下）

## 测试演进（只读位与篡改模拟的相容）

5 个既有篡改检测测试（derived_lineage / evidence_search_guards /
lineage_guards / sqlite_storage / time_travel）直接 ``write_bytes``
改 blob 触发校验——被 0o400 挡住（PermissionError 早于篡改检测）。
处置：各补 ``blob.chmod(0o644)`` 解锁行（注释「故意篡改先解锁」）
——生产防线不动，测试显式声明故意破坏语义。sidecar 单跑即绿
（已知偶发，flake 遥测在案，不计入）。

## 验证

- **全量 1381 passed / 7 skipped**；ruff 过；lint-imports 5/0
- 其余 H 小件核销：manifest "x" 写一次 / 原子写 0600 → 本仓 CAS
  事务性等价已覆盖（tmp+replace + 写后重读校验）；紧凑 JSON →
  序④ checkpoint 负载已用（``separators=(",", ":")``）；
  bounded_task_timeout → 本仓治理等价为动作预算 + decisions 封顶
  （不同抽象层，登记不照搬）。

## 遗留

- model_expect 与 verified 的系统性对照报表（「模型预期 vs 核验
  裁决」偏差率）→ 有 VM 评测数据后随 P6 同批出。
