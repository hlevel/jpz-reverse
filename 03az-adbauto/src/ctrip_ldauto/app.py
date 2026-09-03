from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ctrip_ldauto.business import CtripBusiness, PcapDroidController
from ctrip_ldauto.config import AppRuntimeConfig
from ctrip_ldauto.ld import EmulatorManager, StartedEmulator
from ctrip_ldauto.scheduler import Scheduler
from ctrip_ldauto.strategy import RuleSelector
from ctrip_ldauto.task import TaskService

LOG = logging.getLogger(__name__)


@dataclass
class RunResult:
    code: int
    started: int = 0
    bootstrapped_tasks: int = 0


class CtripLdAutoApp:
    def __init__(self, config: AppRuntimeConfig) -> None:
        self.config = config
        self.stop_event = threading.Event()

    def run(self) -> RunResult:
        LOG.info("Using config: %s", self.config.config_path)
        task_service = TaskService(self.config.xc.task, self.config.system.data_dir)
        try:
            manager = EmulatorManager(self.config.ld)
        except Exception:
            LOG.exception("LDPlayer initialization failed")
            self._wait_before_exit()
            return RunResult(code=2)

        started = manager.start_configured()
        if not started:
            LOG.error("No configured emulator started successfully")
            self._wait_before_exit()
            return RunResult(code=2)

        total_tasks = self._bootstrap_tasks(task_service, started)
        if total_tasks <= 0:
            LOG.error("No task available after bootstrap")
            manager.quit_started_by_us(started)
            self._wait_before_exit()
            return RunResult(code=3, started=len(started))

        pcap = PcapDroidController(
            self.config.xc.app.pcapdroid_package,
            self.config.system.data_dir,
        )
        business = CtripBusiness(self.config.xc.app, pcap)
        scheduler = Scheduler(
            task_service=task_service,
            business=business,
            rule_selector=RuleSelector(self.config.xc.rules),
            stop_event=self.stop_event,
        )

        try:
            scheduler.run(started)
        finally:
            manager.quit_started_by_us(started)

        return RunResult(code=0, started=len(started), bootstrapped_tasks=total_tasks)

    def _bootstrap_tasks(
        self,
        task_service: TaskService,
        started: list[StartedEmulator],
    ) -> int:
        total = 0
        for item in started:
            try:
                total += task_service.bootstrap_instance(item.device.id)
            except Exception:
                LOG.exception("[%s] Task bootstrap failed", item.device.id)
        return total

    def request_stop(self) -> None:
        self.stop_event.set()

    def _wait_before_exit(self) -> None:
        seconds = self.config.system.exit_wait_seconds
        if seconds <= 0:
            return
        LOG.info("Exit after %ss", seconds)
        time.sleep(seconds)


def resolve_path(value: str | None) -> Path | None:
    return Path(value) if value else None
