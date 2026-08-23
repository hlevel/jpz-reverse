from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ctrip_ldauto.config import RuleConfig
from ctrip_ldauto.ld import EmulatorDevice


class BusinessError(RuntimeError):
    pass


@dataclass(frozen=True)
class BusinessResult:
    status: str
    pcap_path: Path | None = None
    detail: dict[str, Any] | None = None


class BusinessModule(Protocol):
    name: str

    def verify_environment(self, device: EmulatorDevice) -> None:
        ...

    def run_task(
        self,
        device: EmulatorDevice,
        task_record: dict[str, Any],
        rule: RuleConfig,
    ) -> BusinessResult:
        ...
