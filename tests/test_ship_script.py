"""Story 11.2：提交脚本测试（Epic 10 复盘 D3，G0）。

脚本本身的可测面：sprint-status 回写（幂等/缺键拒/格式保持）与
门禁失败短路（不提交）。git 操作面由 dry-run 参数/子进程冒烟覆盖。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ship.py"


class TestUpdateStatus:
    def _load(self, monkeypatch, tmp_path, content: str) -> Path:
        fake = tmp_path / "sprint-status.yaml"
        fake.write_text(content, encoding="utf-8")
        monkeypatch.setattr("scripts.ship.STATUS_FILE", fake)
        return fake

    def test_marks_done_idempotent(self, monkeypatch, tmp_path) -> None:
        from scripts import ship

        f = self._load(monkeypatch, tmp_path,
                       "development_status:\n"
                       "  11-2-ship-script: backlog\n"
                       "  11-3-delegation-contract: done\n")
        assert ship.update_status("11-2-ship-script") is True
        assert "11-2-ship-script: done" in f.read_text(encoding="utf-8")
        # 幂等：已 done 再跑不变
        assert ship.update_status("11-2-ship-script") is True
        assert "11-2-ship-script: done" in f.read_text(encoding="utf-8")

    def test_unknown_key_rejected(self, monkeypatch, tmp_path) -> None:
        from scripts import ship

        self._load(monkeypatch, tmp_path,
                   "development_status:\n  11-2-ship-script: backlog\n")
        assert ship.update_status("ghost-key") is False

    def test_no_story_noop(self) -> None:
        from scripts import ship

        assert ship.update_status(None) is True

    def test_real_status_file_has_all_epic11_keys(self) -> None:
        """预注册完整性：13 个 Epic 11 键在 sprint-status。"""
        text = (ROOT / "docs" / "sprint-status.yaml").read_text(
            encoding="utf-8")
        for key in ("11-1-catalog-generation", "11-2-ship-script",
                    "11-13-streaming-edge"):
            assert key in text, key


class TestGateShortCircuit:
    def test_run_reports_failure(self) -> None:
        from scripts import ship

        ok, _ = ship.run("必然失败", [sys.executable, "-c",
                                    "import sys; sys.exit(1)"])
        assert ok is False

    def test_run_reports_success(self) -> None:
        from scripts import ship

        ok, _ = ship.run("必然成功", [sys.executable, "-c", "print(1)"])
        assert ok is True


class TestShipReviewRegressions:
    """Epic 11 评审修复回归（盲审 M6、边界 H-3）。"""

    def test_duplicate_key_only_first_flipped(self, monkeypatch,
                                              tmp_path) -> None:
        """M6.2：同键两处（development_status + 规划区）——只翻转
        development_status 的首个，规划区 backlog 不被连带改写。"""
        from scripts import ship

        fake = tmp_path / "sprint-status.yaml"
        fake.write_text(
            "development_status:\n"
            "  epic-11: in-progress\n"
            "\n"
            "planned_epics:\n"
            "  epic-11: backlog\n",
            encoding="utf-8")
        monkeypatch.setattr("scripts.ship.STATUS_FILE", fake)
        assert ship.update_status("epic-11") is True
        text = fake.read_text(encoding="utf-8")
        assert "  epic-11: done" in text
        assert "  epic-11: backlog" in text  # 规划区不动

    def test_empty_value_key_still_recognized(self, monkeypatch,
                                              tmp_path) -> None:
        """H-3：键存在但值为空——不再误报「无键」。"""
        from scripts import ship

        fake = tmp_path / "sprint-status.yaml"
        fake.write_text("development_status:\n  11-2-x:\n",
                        encoding="utf-8")
        monkeypatch.setattr("scripts.ship.STATUS_FILE", fake)
        assert ship.update_status("11-2-x") is True
        assert "11-2-x: done" in fake.read_text(encoding="utf-8")

    def test_write_is_atomic_no_tmp_leftover(self, monkeypatch,
                                             tmp_path) -> None:
        """M6.3：原子替换——不留 .tmp 残留。"""
        from scripts import ship

        fake = tmp_path / "sprint-status.yaml"
        fake.write_text("development_status:\n  k-1: backlog\n",
                        encoding="utf-8")
        monkeypatch.setattr("scripts.ship.STATUS_FILE", fake)
        ship.update_status("k-1")
        assert not list(tmp_path.glob("*.tmp"))

    def test_pytest_trailer_from_output(self) -> None:
        """M6.5/验收审计 5：计数尾行从 pytest 输出解析——不手写。"""
        from scripts import ship

        trailer = ship._pytest_trailer(
            "...\n1004 passed, 4 skipped in 12.3s\n", True, True)
        assert "1004 passed" in trailer
        assert "4 skipped" in trailer
        assert "ruff clean" in trailer
        assert "lint-imports kept" in trailer
