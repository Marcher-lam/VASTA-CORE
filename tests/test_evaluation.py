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


class TestReviewGuards:
    """Epic 4-7 code-review 修复的守卫（复现/规则/失败分类/多种子/配置）。"""

    def test_task_seed_stable_across_processes(self) -> None:
        """评审实锤：hash(task_id) 播种跨进程漂移（net_gain 0.32 vs 0.44）。

        子进程两跑必须得到同一首随机数（crc32 播种）。"""
        import subprocess
        import sys

        code = (
            "from vasta_eval.evaluation import task_rng_seed\n"
            "import random\n"
            "print(random.Random(task_rng_seed(9, 'vl-00')).random())\n"
        )
        outs = [
            subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True
            ).stdout.strip()
            for _ in range(2)
        ]
        assert outs[0] == outs[1]

    def test_report_reproducible_same_seed(self) -> None:
        """同 seed 两次完整消融 → 逐组逐字段一致（FR-063）。"""
        tasks = generate_tasks(8, seed=3)
        config = make_config(task_ids=[t.task_id for t in tasks], seed=3)
        r1 = run_ablation(tasks, config).to_summary()
        r2 = run_ablation(tasks, config).to_summary()
        assert r1 == r2

    def test_solve_reaches_goal_for_all_rules(self) -> None:
        """评审修复：solve 为真实转移上的 BFS——全部隐藏规则可证达。"""
        from vasta_eval import VastaLabTask

        for rule in ("none", "teleport", "wind"):
            for size in (4, 5):
                t = VastaLabTask(
                    task_id=f"chk-{rule}-{size}", grid_size=size,
                    start=(0, 0), goal=(size - 1, size - 1), hidden_rule=rule,
                )
                assert t.run_agent(t.solve()), (rule, size)

    def test_wind_has_transition_effect(self) -> None:
        """评审实锤：wind 原先无转移语义（纯装饰字段）。"""
        from vasta_eval import VastaLabTask

        calm = VastaLabTask(task_id="calm", start=(0, 0), goal=(3, 3))
        windy = VastaLabTask(
            task_id="windy", start=(0, 0), goal=(3, 3), hidden_rule="wind"
        )
        # 同一动作序列在 wind 下落到不同位置（偶数步顺风波 +1 行）
        assert calm._pos_after(["right", "up"]) != windy._pos_after(["right", "up"])

    def test_teleport_changes_position(self) -> None:
        from vasta_eval import VastaLabTask

        t = VastaLabTask(
            task_id="tp", start=(0, 0), goal=(3, 3), hidden_rule="teleport"
        )
        assert t._pos_after(["down", "right"]) == (2, 2)  # 踩 (1,1) 即传送

    def test_failure_breakdown_categorized(self) -> None:
        """评审修复：失败按 kind 分类（原为单一 failed 桶）。"""
        from vasta_eval import FAILURE_KINDS

        tasks = generate_tasks(12, seed=5)
        config = make_config(task_ids=[t.task_id for t in tasks], seed=5)
        report = run_ablation(tasks, config)
        baseline = next(g for g in report.groups if g.group == "baseline")
        breakdown = baseline.failure_breakdown
        if not baseline.results[0].success:  # 有失败时
            assert set(breakdown) <= set(FAILURE_KINDS) | {"all_passed"}
        # 成功项 failure_kind 为 None；失败项必有合法 kind
        for r in baseline.results:
            if not r.success:
                assert r.failure_kind in FAILURE_KINDS

    def test_multi_seed_aggregation_with_stddev(self) -> None:
        """评审修复：多种子聚合 + 成功率标准差（方差可见）。"""
        tasks = generate_tasks(10, seed=1)
        config = make_config(task_ids=[t.task_id for t in tasks], seed=1)
        report = run_ablation(tasks, config, n_seeds=3)
        for group in report.groups:
            assert group.seeds_run == 3
            assert len(group.results) == 3 * len(tasks)
            assert group.success_rate_stddev >= 0.0

    def test_verify_config_complete_budget_required(self) -> None:
        """评审修复：budget 缺失/非法原也判 True。"""
        from vasta_eval import EvaluationConfig, verify_config_complete

        ok = EvaluationConfig(
            task_ids=["t1"], seed=1, code_version="v", budget={"max_actions": 10}
        )
        assert verify_config_complete(ok)
        bad_budget = EvaluationConfig(
            task_ids=["t1"], seed=1, code_version="v", budget={}
        )
        assert not verify_config_complete(bad_budget)
        bad_value = EvaluationConfig.model_validate(
            {"task_ids": ["t1"], "seed": 1, "code_version": "v",
             "budget": {"max_actions": 0}}
        )
        assert not verify_config_complete(bad_value)


class TestAblationSlicing:
    """FR-064「切片」：维度切分消融（验收矩阵行动项 2）。"""

    def test_slice_by_hidden_rule(self) -> None:
        """按隐藏规则切片：每片独立六组，净增益可按任务族拆读。"""
        from vasta_eval import run_ablation_slices

        tasks = generate_tasks(8, seed=11)
        config = make_config(task_ids=[t.task_id for t in tasks], seed=11)
        reports = run_ablation_slices(
            tasks, config, slice_fn=lambda t: t.hidden_rule
        )
        assert set(reports) == {"none", "teleport", "wind"}  # 全部任务族
        total = 0
        for report in reports.values():
            assert [g.group for g in report.groups] == [
                "baseline", "evidence", "cognition", "contract", "model", "full",
            ]
            total += len(report.groups[0].results)
        assert total == len(tasks)  # 切片不重不漏

    def test_slice_by_variant_suffix(self) -> None:
        from vasta_eval import run_ablation_slices

        tasks = generate_tasks(4, seed=2)
        config = make_config(task_ids=[t.task_id for t in tasks], seed=2)

        def variant(task) -> str:
            if task.task_id.endswith("-noise"):
                return "noise"
            if task.task_id.endswith("-dev"):
                return "deviation"
            return "main"

        reports = run_ablation_slices(tasks, config, slice_fn=variant)
        assert set(reports) == {"main", "noise", "deviation"}
        assert len(reports["noise"].groups[0].results) == 4  # n_main 噪声变体

    def test_task_ids_subset_slicing(self) -> None:
        """task_ids 子集切片：未知任务报错，子集内运行。"""
        tasks = generate_tasks(4, seed=5)
        config = make_config(task_ids=[t.task_id for t in tasks], seed=5)
        subset = [t.task_id for t in tasks[:3]]
        report = run_ablation(tasks, config, groups=("baseline", "full"),
                              task_ids=subset)
        assert len(report.groups) == 2
        assert len(report.groups[0].results) == 3
        with pytest.raises(ValueError):
            run_ablation(tasks, config, task_ids=["vl-99"])

    def test_slice_net_gain_per_family_readable(self) -> None:
        """切片后的每族净增益可独立读取（不再只剩全池单一数字）。"""
        from vasta_eval import run_ablation_slices

        tasks = generate_tasks(8, seed=11)  # 该样本含全部三族规则
        config = make_config(task_ids=[t.task_id for t in tasks], seed=11)
        reports = run_ablation_slices(
            tasks, config, slice_fn=lambda t: t.hidden_rule
        )
        gains = {label: r.full_vs_baseline_net_gain
                 for label, r in reports.items()}
        assert set(gains) == {"none", "teleport", "wind"}
        assert all(isinstance(v, float) for v in gains.values())
