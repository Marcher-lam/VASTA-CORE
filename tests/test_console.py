"""Story 10.14：Console 最小可用面（NFR-012/013 收口）。

无障碍（skip link/原生元素/label 关联/表格 caption+scope/lang 地标）+
国际化（双语目录/时间/数字/事件描述）+ 可读对比（payload 点分路径
四组两栏）——事件语义不随语言切换变化。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vasta_protocols.sequencer import EventSequencer
from vasta_storage import SqliteStorage
from vastacore.ops.console import (
    describe_event,
    format_number,
    format_ts,
    mount_console,
)

TOKEN = "console-test-token"


@pytest.fixture
def client(tmp_path):
    store = SqliteStorage(tmp_path / "s")
    seq = EventSequencer(store, "run-1",
                         tenant_id="t-default", project_id="p-default")
    import asyncio

    async def seed() -> None:
        await seq.emit("run.started", {"goal": "demo"})
        await seq.emit("observation.decision",
                       {"detail": {"status": "pending"}, "tick": 1,
                        "pending_only": True})
        await seq.emit("action.contracted", {"tool": "set_status",
                                             "risk": "R2"})
        await seq.emit("action.policy_cleared", {"decision": "allow",
                                                 "risk_effective": "R2"})
        await seq.emit("action.executed", {"tool": "set_status",
                                           "detail": {"status": "pending"}})
        await seq.emit("verification.passed", {"tool": "set_status",
                                               "matched": 1})
        await seq.emit("observation.decision",
                       {"detail": {"status": "done"}, "tick": 1,
                        "done_only": True})

    asyncio.run(seed())
    app = FastAPI()
    mount_console(app, store=store, token=TOKEN)
    with TestClient(app) as c:
        yield c
    store.close()


def _auth(c: TestClient):
    c.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return c


class TestAccessControl:
    def test_all_pages_require_token(self, client) -> None:
        for path in ("/console", "/console/runs/run-1",
                     "/console/runs/run-1/compare?before=4&after=5"):
            assert client.get(path).status_code == 401, path

    def test_unknown_run_404(self, client) -> None:
        assert _auth(client).get("/console/runs/ghost").status_code == 404


class TestAccessibility:
    def test_skip_link_first_focusable(self, client) -> None:
        html = _auth(client).get("/console").text
        first_anchor = html[html.index("<a "):]
        assert first_anchor.startswith('<a class="skip"'), \
            "首个可聚焦元素必须是跳转链接（NFR-012）"
        assert 'href="#main"' in first_anchor

    def test_native_elements_no_js_handlers(self, client) -> None:
        html = _auth(client).get("/console").text
        assert "onclick" not in html and "javascript:" not in html
        for anchor in html.split("<a ")[1:]:
            assert 'href="' in anchor, "全部链接必须有 href（键盘可达）"

    def test_form_label_associated(self, client) -> None:
        html = _auth(client).get("/console").text
        assert '<label for="run-id">' in html
        assert '<input id="run-id"' in html

    def test_table_caption_and_scope(self, client) -> None:
        html = _auth(client).get("/console/runs/run-1").text
        assert "<caption>" in html
        assert '<th scope="col">' in html

    def test_landmarks_and_lang(self, client) -> None:
        html = _auth(client).get("/console").text
        assert '<html lang="zh-CN">' in html
        assert "<main" in html and "<nav" in html


class TestI18n:
    def test_locale_switch_changes_catalog_and_lang(self, client) -> None:
        zh = _auth(client).get("/console").text
        en = _auth(client).get("/console?lang=en").text
        assert '<html lang="zh-CN">' in zh
        assert '<html lang="en">' in en
        assert "运行检索" in zh and "Run lookup" in en
        assert zh != en

    def test_time_localization_differs(self, client) -> None:
        zh = _auth(client).get("/console/runs/run-1").text
        en = _auth(client).get("/console/runs/run-1?lang=en").text
        # 同一时间两种呈现（zh: 2026-… 24h 制无 AM/PM；en: 英文月名 + AM/PM）
        assert "AM" not in zh and "PM" not in zh
        assert "AM" in en or "PM" in en
        assert any(m in en for m in
                   ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
                    "Aug", "Sep", "Oct", "Nov", "Dec"))

    def test_number_grouping(self) -> None:
        assert format_number(1000000, "en") == "1,000,000"
        assert format_number(1000000, "zh-CN") == "1,000,000"

    def test_ts_formats(self) -> None:
        ts = "2026-11-06T14:30:05+00:00"
        zh = format_ts(ts, "zh-CN")
        en = format_ts(ts, "en")
        assert zh == "2026-11-06 14:30:05"
        assert en == "06 Nov 2026, 02:30:05 PM"
        assert zh != en

    def test_event_descriptions_localized(self, client) -> None:
        zh = _auth(client).get("/console/runs/run-1").text
        en = _auth(client).get("/console/runs/run-1?lang=en").text
        assert "动作契约建立" in zh and "Action contract established" in en

    def test_describe_event_fallback_and_stability(self) -> None:
        # 目录未命中回退原始类型（两语言一致——事件语义稳定）
        assert describe_event("memory.published", "zh-CN") == \
            "memory.published"
        assert describe_event("memory.published", "en") == "memory.published"
        # 目录命中两语言不同话术、同一语言稳定
        assert describe_event("action.policy_denied", "zh-CN") == "策略拒绝"
        assert describe_event("action.policy_denied", "en") == "Policy denied"


class TestReadableCompare:
    def test_compare_groups_and_aria(self, client) -> None:
        resp = _auth(client).get(
            "/console/runs/run-1/compare?before=1&after=6")
        assert resp.status_code == 200
        html = resp.text
        assert "变更项" in html and "Changed" not in html  # zh 缺省
        # 四组表格（caption 语义组名）
        for group in ("变更项", "仅前项存在", "仅后项存在", "相同项"):
            assert f"<caption>{group}</caption>" in html, group
        # 变更行有视觉标记类（.changed 背景——可读对比）
        assert 'class="changed"' in html

    def test_compare_english(self, client) -> None:
        html = _auth(client).get(
            "/console/runs/run-1/compare?before=1&after=6&lang=en").text
        for group in ("Changed", "Only in before", "Only in after",
                      "Unchanged"):
            assert f"<caption>{group}</caption>" in html

    def test_compare_bad_seq_404(self, client) -> None:
        assert _auth(client).get(
            "/console/runs/run-1/compare?before=98&after=99").status_code \
            == 404

    def test_lookup_redirects(self, client) -> None:
        resp = _auth(client).get(
            "/console/runs/__lookup__?run_id=run-1", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("/console/runs/run-1")


class TestEventSemanticsStable:
    def test_rendering_does_not_write_events(self, client, tmp_path) -> None:
        """渲染零写侧（展示层只读——事件语义稳定）。"""
        store = SqliteStorage(tmp_path / "s")
        n_before = sum(1 for _ in store.iter_run_events("run-1"))
        _auth(client).get("/console/runs/run-1")
        _auth(client).get("/console/runs/run-1/compare?before=1&after=6")
        _auth(client).get("/console?lang=en")
        n_after = sum(1 for _ in store.iter_run_events("run-1"))
        assert n_before == n_after == 7
        store.close()
