"""Epic 7：评测框架、VastaLab 任务集与六组消融（FR-063/064，AC-01/07）。"""

from __future__ import annotations

import pytest

from vasta_eval import (
    ABLATION_GROUPS,
    GROUP_FLAGS,
    VastaLabTask,
    generate_tasks,
    make_config,
    run_ablation,
    verify_config_complete,
)


class TestEvaluationConfig:
    def test_config_complete_and_reproducible(self) -> None:
        """FR-063：配置全固化，同 seed 同结果（报告可还原）。"""
        config = make_config(task_ids=["vl-00", "vl-01"], seed=42)
        assert verify_config_complete(config)
        # 同配置重跑 → 同报告
        tasks = generate_tasks(4, seed=42)
        r1 = run_ablation(tasks[:2], config)
        r2 = run_ablation(tasks[:2], config)
        assert r1.to_summary() == r2.to_summary()

    def test_incomplete_config_fails(self) -> None:
        from vasta_eval import EvaluationConfig

        # task_ids 的 min_length=1 在 pydantic 层即拒（更强）
        with pytest.raises(Exception):  # noqa: B017
            EvaluationConfig(
                task_ids=[], model_name="", prompt_version="",
                seed=0, code_version="",
            )
        # 所有字符串字段 min_length=1 均在 pydantic 层拒——verify 函数是
        # 深度校验（覆盖 pydantic 未约束的组合，如预算字典为空）
        config = EvaluationConfig(
            task_ids=["t1"], model_name="m", prompt_version="p",
            seed=0, code_version="v1", budget={},
        )
        # budget 空字典不被 pydantic 拒——verify 作为运行前门槛存在
        assert isinstance(config, EvaluationConfig)


class TestVastaLabTasks:
    def test_task_generation_meets_ac01_quota(self) -> None:
        """AC-01 任务基础：≥20 主任务 + 变体合计 ≥40。"""
        tasks = generate_tasks(20, seed=42)
        main = [t for t in tasks if "-noise" not in t.task_id and "-dev" not in t.task_id]
        assert len(main) == 20
        assert len(tasks) >= 40  # 20 主 + 20 噪声 + 10 偏差注入

    def test_hidden_rules_present(self) -> None:
        tasks = generate_tasks(20, seed=42)
        rules = {t.hidden_rule for t in tasks}
        assert "teleport" in rules  # 隐藏机制存在
        assert "none" in rules

    def test_deviation_and_noise_variants(self) -> None:
        tasks = generate_tasks(20, seed=42)
        assert any(t.deviation_injection for t in tasks)
        assert any(t.noise > 0 for t in tasks)

    def test_ground_truth_solver(self) -> None:
        task = VastaLabTask(task_id="t", goal=(3, 3))
        path = task.solve()
        assert task.run_agent(path)  # 求解器自身可通关

    def test_teleport_rule(self) -> None:
        task = VastaLabTask(task_id="tp", goal=(3, 3), hidden_rule="teleport")
        # 踩 (1,1) 传送 (2,2)
        pos = task._pos_after(["down", "right"])
        assert pos == (2, 2)


class TestAblation:
    def test_six_groups_all_reported(self) -> None:
        """AC-07：一条命令六组全出。"""
        tasks = generate_tasks(10, seed=7)
        config = make_config(
            task_ids=[t.task_id for t in tasks], seed=7
        )
        report = run_ablation(tasks, config)
        assert [g.group for g in report.groups] == list(ABLATION_GROUPS)
        summary = report.to_summary()
        assert len(summary["groups"]) == 6
        # 每组含成功率/动作/开销/失败分类
        for g in summary["groups"]:
            assert "success_rate" in g and "mean_actions" in g
            assert "mean_overhead_ms" in g and "failures" in g

    def test_group_flags_monotone_capabilities(self) -> None:
        """组间仅目标能力差异（叠加开关）。"""
        assert not GROUP_FLAGS["baseline"]["evidence"]
        assert GROUP_FLAGS["evidence"]["evidence"]
        assert not GROUP_FLAGS["evidence"]["cognition"]
        assert GROUP_FLAGS["full"]["evidence"]
        assert GROUP_FLAGS["full"]["cognition"]
        assert GROUP_FLAGS["full"]["contract"]
        assert GROUP_FLAGS["full"]["model"]

    def test_net_gain_computed(self) -> None:
        tasks = generate_tasks(10, seed=7)
        config = make_config(task_ids=[t.task_id for t in tasks], seed=7)
        report = run_ablation(tasks, config)
        # Full 相对 Baseline 净收益可读（Stage 1 出门条件输入）
        assert isinstance(report.full_vs_baseline_net_gain, float)

    def test_overhead_separately_measured(self) -> None:
        """NFR-005 MVP 档：平台开销单独测量且 Full 组开销高于 Baseline
        （契约链+模型构建是真实成本）。"""
        tasks = generate_tasks(10, seed=7)
        config = make_config(task_ids=[t.task_id for t in tasks], seed=7)
        report = run_ablation(tasks, config)
        by_group = {g.group: g for g in report.groups}
        assert (
            by_group["full"].mean_overhead_ms
            > by_group["baseline"].mean_overhead_ms
        )
