from __future__ import annotations

import logging
import time
from typing import Any

from ctrip_ldauto.config import AppConfig, RuleConfig
from ctrip_ldauto.ld import EmulatorDevice

from .base import BusinessError, BusinessResult
from .pcapdroid import PcapDroidController

LOG = logging.getLogger(__name__)


class CtripBusiness:
    name = "ctrip"

    def __init__(self, app_config: AppConfig, pcap: PcapDroidController) -> None:
        self.app_config = app_config
        self.pcap = pcap

    def verify_environment(self, device: EmulatorDevice) -> None:
        missing: list[str] = []
        if not device.adb.is_package_installed(self.app_config.ctrip_package):
            missing.append(self.app_config.ctrip_package)
        if not device.adb.is_package_installed(self.app_config.pcapdroid_package):
            missing.append(self.app_config.pcapdroid_package)
        if missing:
            raise BusinessError(f"[{device.id}] missing app package(s): {', '.join(missing)}")
        LOG.info("[%s] Required app packages are installed", device.id)

    def run_task(
        self,
        device: EmulatorDevice,
        task_record: dict[str, Any],
        rule: RuleConfig,
    ) -> BusinessResult:
        task = task_record.get("task") or {}
        hotel_name = str(task.get("hotel_name") or task.get("hotel") or task.get("name") or "")
        check_in = str(task.get("check_in") or task.get("start_date") or task.get("date") or "")
        check_out = str(task.get("check_out") or task.get("end_date") or "")

        LOG.info(
            "[%s] Running ctrip task %s hotel=%s check_in=%s check_out=%s",
            device.id,
            task_record.get("_local_id"),
            hotel_name,
            check_in,
            check_out,
        )

        self.pcap.start_capture(device)
        device.adb.start_app(self.app_config.ctrip_package)
        self._enter_hotel_search(device, task)
        self._browse_detail(device, rule.browse_seconds)
        pcap_path = self.pcap.stop_capture(device)

        if pcap_path is None:
            return BusinessResult(
                status="pcap_missing",
                detail={"reason": "PCAPdroid did not expose a pcap file in known directories"},
            )
        return BusinessResult(status="pcap_saved", pcap_path=pcap_path)

    def _enter_hotel_search(self, device: EmulatorDevice, task: dict[str, Any]) -> None:
        LOG.info("[%s] Ctrip hotel page automation placeholder reached", device.id)
        # v1 intentionally stops at the automation boundary. The next module
        # should add page-specific templates/coordinates for: hotel tab, date
        # picker, hotel keyword input, search result wait, and hotel matching.

    def _browse_detail(self, device: EmulatorDevice, seconds: int) -> None:
        LOG.info("[%s] Browsing detail placeholder for %ss", device.id, seconds)
        time.sleep(max(0, seconds))
        try:
            device.adb.back()
        except Exception:
            LOG.debug("[%s] Back after browse failed", device.id, exc_info=True)
