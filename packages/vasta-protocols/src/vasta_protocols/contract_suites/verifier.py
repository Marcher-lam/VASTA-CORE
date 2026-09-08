"""Verifier 契约：四态枚举与清单声明。"""

from __future__ import annotations

from ..protocols import Verifier

_OUTCOMES = {"pass", "deviation", "inconclusive", "system_error"}


class VerifierContract:
    def make_verifier(self) -> Verifier:
        raise NotImplementedError("verifier package must provide make_verifier()")

    async def test_manifest_declared(self) -> None:
        manifest = self.make_verifier().manifest
        assert manifest.name and manifest.version and manifest.kind

    async def test_outcome_in_four_states(self) -> None:
        result = await self.make_verifier().verify("contract:stub", evidence={})
        assert result.outcome in _OUTCOMES
