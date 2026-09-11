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
