"""vastacore.agents 子包（Stage 5——多 Agent 平台化，复评十裁决：
Stage 5 新增多 Agent 模块进本子包，governance 维持平铺）。"""

from .delegation import DelegationContract, complete_delegation, delegate, validate_action

__all__ = ["DelegationContract", "complete_delegation", "delegate",
           "validate_action"]
