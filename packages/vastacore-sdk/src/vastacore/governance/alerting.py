"""告警规则与指标快照（Story 9.12 起，Story 10.4 评审修复 F3
自 ops 下沉至 governance——governance 不得反向依赖 ops 层）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError

_SEVERITIES = ("sev1", "sev2", "sev3")


class MetricsSnapshot(BaseModel):
    """服务指标快照（MVP 形态——JSON /metrics 的数据面）。"""

    model_config = ConfigDict(extra="forbid")

    error_rate: float = Field(default=0.0, ge=0.0)
    queue_depth: int = Field(default=0, ge=0)
    quota_throttled: int = Field(default=0, ge=0)
    sessions_active: int = Field(default=0, ge=0)
    extra: dict[str, float] = Field(default_factory=dict)


class AlertRule(BaseModel):
    """阈值规则：metric > threshold 即触发。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    metric: str  # error_rate | queue_depth | quota_throttled | extra 键
    threshold: float
    severity: str = "sev3"  # _SEVERITIES

    def model_post_init(self, __context: Any) -> None:
        if self.severity not in _SEVERITIES:
            raise VastaError(
                code="ops.bad_severity",
                message=f"severity 须为 {_SEVERITIES}（得到 {self.severity!r}）",
            )


class Alert(BaseModel):
    """触发中的告警。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    metric: str
    value: float
    threshold: float
    severity: str


def default_alert_rules() -> list[AlertRule]:
    """关键指标基线规则（错误率 / 队列深 / 配额触顶——AC 字面）。"""
    return [
        AlertRule(name="error_rate_high", metric="error_rate",
                  threshold=0.05, severity="sev1"),
        AlertRule(name="queue_depth_high", metric="queue_depth",
                  threshold=100, severity="sev2"),
        AlertRule(name="quota_throttling", metric="quota_throttled",
                  threshold=10, severity="sev2"),
    ]


def evaluate_alerts(
    snapshot: MetricsSnapshot,
    rules: list[AlertRule] | None = None,
) -> list[Alert]:
    """规则评估：metric > threshold 触发（严格大于——恰好达标不告警）。"""
    rules = rules if rules is not None else default_alert_rules()
    values: dict[str, float] = {
        "error_rate": snapshot.error_rate,
        "queue_depth": float(snapshot.queue_depth),
        "quota_throttled": float(snapshot.quota_throttled),
        "sessions_active": float(snapshot.sessions_active),
        **snapshot.extra,
    }
    alerts: list[Alert] = []
    for rule in rules:
        value = values.get(rule.metric)
        if value is None:
            raise VastaError(
                code="ops.unknown_metric",
                message=(f"规则 {rule.name!r} 引用未知指标 {rule.metric!r}"
                         "（快照未携带）"),
            )
        if value > rule.threshold:
            alerts.append(Alert(name=rule.name, metric=rule.metric,
                                value=value, threshold=rule.threshold,
                                severity=rule.severity))
    return alerts




__all__ = ["Alert", "AlertRule", "MetricsSnapshot",
           "default_alert_rules", "evaluate_alerts"]
