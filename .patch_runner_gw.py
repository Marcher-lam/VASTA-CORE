import re

p = "packages/vasta-runtime/src/vasta_runtime/runner.py"
s = open(p, encoding="utf-8").read()

old = """        supervisor: Supervisor | None = None,
        capture_observations: bool = False,
        safety_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.env = env
        self.store = store
        self.supervisor = supervisor or Supervisor()"""
new = """        supervisor: Supervisor | None = None,
        capture_observations: bool = False,
        safety_clock: Callable[[], datetime] | None = None,
        tool_gateway: "ToolGateway | None" = None,
    ) -> None:
        self.env = env
        self.store = store
        self.supervisor = supervisor or Supervisor()
        # AD-4：业务工具凭证只存在于网关；引擎不持有任何 ToolAdapter。
        self.tool_gateway = tool_gateway"""
assert old in s
s = s.replace(old, new)

old = """        capture_observations: bool = False,
        safety_clock: Callable[[], datetime] | None = None,
    ) -> RunEngine:
        engine = cls(
            env=env,
            store=store,
            budget=budget,
            config=config,
            clock=clock,
            run_context=run_context,
            supervisor=supervisor,
            capture_observations=capture_observations,
            safety_clock=safety_clock,
        )"""
new = """        capture_observations: bool = False,
        safety_clock: Callable[[], datetime] | None = None,
        tool_gateway: "ToolGateway | None" = None,
    ) -> RunEngine:
        engine = cls(
            env=env,
            store=store,
            budget=budget,
            config=config,
            clock=clock,
            run_context=run_context,
            supervisor=supervisor,
            capture_observations=capture_observations,
            safety_clock=safety_clock,
            tool_gateway=tool_gateway,
        )"""
assert old in s
s = s.replace(old, new)

old = "from .contracted import ContractedMixin"
new = "from .contracted import ContractedMixin\nfrom .gateway import ToolGateway"
assert old in s
s = s.replace(old, new)

open(p, "w", encoding="utf-8", newline="\n").write(s)
print("runner wired")
