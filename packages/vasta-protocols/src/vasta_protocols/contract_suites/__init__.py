"""契约测试套件：每类端口一个可复用基类。

约定（脊柱 Conventions）：vasta-protocols 提供每类端口的契约测试套件，
每个适配器/插件必须通过对应套件才能合入。

**运行要求**：套件含 async 测试，需 pytest-asyncio 且
`asyncio_mode = "auto"`（本仓库已配于根 pyproject）；第三方环境请同样配置，
否则 async 用例将被静默跳过。

用法：实现方在自己的测试模块继承基类并实现 make_* 工厂，例如::

    from vasta_protocols.contract_suites import EnvironmentAdapterContract

    class TestGridWorldAdapter(EnvironmentAdapterContract):
        def make_adapter(self):
            return GridWorldAdapter()
"""

from .environment import EnvironmentAdapterContract
from .event_envelope import EventEnvelopeContract
from .event_log import EventLogContract
from .model import ModelAdapterContract
from .storage import StorageAdapterContract
from .tool import ToolAdapterContract
from .verifier import VerifierContract

__all__ = [
    "EnvironmentAdapterContract",
    "EventEnvelopeContract",
    "EventLogContract",
    "ModelAdapterContract",
    "StorageAdapterContract",
    "ToolAdapterContract",
    "VerifierContract",
]
