from __future__ import annotations

from dataclasses import dataclass

from ctrip_ldauto.config import InstanceConfig

from .adb import AdbDevice


@dataclass(frozen=True)
class EmulatorDevice:
    instance: InstanceConfig
    adb: AdbDevice

    @property
    def id(self) -> str:
        return self.instance.id

    @property
    def index(self) -> int:
        return self.instance.index

    @property
    def name(self) -> str:
        return self.instance.name
