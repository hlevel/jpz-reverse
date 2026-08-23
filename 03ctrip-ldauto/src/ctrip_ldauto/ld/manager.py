from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ctrip_ldauto.config import InstanceConfig, LdConfig

from .adb import AdbDevice
from .device import EmulatorDevice
from .ldconsole import LDConsoleClient, LDConsoleError

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartedEmulator:
    device: EmulatorDevice
    already_running: bool


class EmulatorManager:
    def __init__(self, config: LdConfig) -> None:
        self.config = config
        self.ldconsole = LDConsoleClient(config)
        self.adb_path = self.ldconsole.adb_path(config.adb_path)

    def start_configured(self) -> list[StartedEmulator]:
        started: list[StartedEmulator] = []
        for instance in self.config.instances:
            try:
                item = self._start_one(instance)
            except Exception:
                LOG.exception("Failed to start emulator %s(%s)", instance.id, instance.index)
                continue
            started.append(item)
        return started

    def _start_one(self, instance: InstanceConfig) -> StartedEmulator:
        already_running = self.ldconsole.is_running_instance(instance)
        if already_running:
            LOG.info("Emulator %s is already running", instance.id)
        else:
            LOG.info("Launching emulator %s(%s)", instance.id, instance.index)
            self.ldconsole.launch_instance(instance)

        serial = self.ldconsole.serial_instance(instance)
        adb = AdbDevice(Path(self.adb_path), serial)
        if not adb.wait_ready(self.config.wait_device_ready_seconds):
            raise LDConsoleError(f"ADB not ready for {instance.id}: {serial}")

        LOG.info("Emulator %s ready with serial %s", instance.id, serial)
        return StartedEmulator(
            device=EmulatorDevice(instance=instance, adb=adb),
            already_running=already_running,
        )

    def quit_started_by_us(self, items: list[StartedEmulator]) -> None:
        for item in items:
            if item.already_running:
                LOG.info("Skip closing emulator %s because it was already running", item.device.id)
                continue
            try:
                LOG.info("Closing emulator %s", item.device.id)
                self.ldconsole.quit_instance(item.device.instance)
            except Exception:
                LOG.exception("Failed to close emulator %s", item.device.id)
