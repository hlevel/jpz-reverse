from __future__ import annotations

import logging
import threading

from ctrip_ldauto.business import BusinessModule
from ctrip_ldauto.ld import StartedEmulator
from ctrip_ldauto.strategy import RuleSelector
from ctrip_ldauto.task import TaskService

LOG = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        task_service: TaskService,
        business: BusinessModule,
        rule_selector: RuleSelector,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.task_service = task_service
        self.business = business
        self.rule_selector = rule_selector
        self.stop_event = stop_event or threading.Event()

    def run(self, emulators: list[StartedEmulator]) -> None:
        threads = [
            threading.Thread(
                target=self._run_worker,
                name=f"emu-{item.device.id}",
                args=(item,),
                daemon=False,
            )
            for item in emulators
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    def _run_worker(self, item: StartedEmulator) -> None:
        device = item.device
        rule = self.rule_selector.for_instance(device.id)
        LOG.info("[%s] Worker started with rule %s", device.id, rule.name)

        try:
            self.business.verify_environment(device)
        except Exception:
            LOG.exception("[%s] Environment verification failed", device.id)
            return

        while not self.stop_event.is_set():
            record = self.task_service.claim_or_receive(device.id)
            if not record:
                LOG.info("[%s] No task available; worker exits in v1", device.id)
                return

            local_id = str(record["_local_id"])
            self.task_service.mark(device.id, local_id, "running")
            try:
                result = self.business.run_task(device, record, rule)
                self.task_service.mark(
                    device.id,
                    local_id,
                    result.status,
                    pcap_path=str(result.pcap_path) if result.pcap_path else "",
                    detail=result.detail or {},
                )
                if result.pcap_path:
                    self.task_service.upload_pcap(device.id, record, result.pcap_path)
            except Exception as exc:
                LOG.exception("[%s] Task failed: %s", device.id, local_id)
                self.task_service.mark(device.id, local_id, "failed", error=str(exc))

            if rule.task_rest_seconds > 0:
                LOG.info("[%s] Resting %ss after task", device.id, rule.task_rest_seconds)
                self.stop_event.wait(rule.task_rest_seconds)
