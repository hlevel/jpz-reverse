from __future__ import annotations

from ctrip_ldauto.config import RuleConfig


class RuleSelector:
    def __init__(self, rules: list[RuleConfig]) -> None:
        self.rules = rules

    def for_instance(self, instance_id: str) -> RuleConfig:
        for rule in self.rules:
            if not rule.instance_ids or instance_id in rule.instance_ids:
                return rule
        return self.rules[0]
