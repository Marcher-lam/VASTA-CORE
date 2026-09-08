"""统一错误信封（约定）：{code, message, retryable, run_id, event_id}。"""

from __future__ import annotations


class VastaError(Exception):
    """携带错误信封字段的基异常。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        run_id: str | None = None,
        event_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.run_id = run_id
        self.event_id = event_id

    def envelope(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "run_id": self.run_id,
            "event_id": self.event_id,
        }


class DuplicateEventError(VastaError):
    """(run_id, seq) 唯一约束冲突（AD-2）。"""

    def __init__(self, run_id: str, seq: int) -> None:
        super().__init__(
            code="event.duplicate_seq",
            message=f"run {run_id} already has an event at seq {seq}",
            retryable=False,
            run_id=run_id,
        )
        self.seq = seq
