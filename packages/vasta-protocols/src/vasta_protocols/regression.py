"""回归任务契约（FR-062，评审修复：从 vasta-storage 上移至依赖根）。

复现包 → 回归任务 是「存储投影 ↔ 评测框架」的跨包接口，按 AD-1
契约归 vasta-protocols（vasta-storage 保留兼容再导出）。格式版本
semver（AD-9）：不兼容变更必须递增 REGRESSION_FORMAT_VERSION 主版本。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: 回归任务格式版本（AD-9 semver）。
REGRESSION_FORMAT_VERSION = "1.0.0"


class RegressionTask(BaseModel):
    """回归任务登记（评测框架可直接消费的契约格式）。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    kind: str = "replay_regression"
    format_version: str = Field(default=REGRESSION_FORMAT_VERSION)
    event_data: list[dict[str, Any]] = Field(default_factory=list)
    expected_outcome: str = "non_model_events_replayable"
    created_at: str = ""


__all__ = ["REGRESSION_FORMAT_VERSION", "RegressionTask"]
