from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from ctrip_ldauto.ld import EmulatorDevice

LOG = logging.getLogger(__name__)


class PcapDroidController:
    def __init__(self, package: str, data_dir: Path) -> None:
        self.package = package
        self.data_dir = data_dir

    def start_capture(self, device: EmulatorDevice) -> None:
        LOG.info("[%s] Opening PCAPdroid", device.id)
        device.adb.start_app(self.package)
        # v1 keeps coordinates out of core code. The concrete click flow belongs
        # in the business page script once coordinates/templates are available.

    def stop_capture(self, device: EmulatorDevice) -> Path | None:
        LOG.info("[%s] Stopping PCAPdroid capture", device.id)
        device.adb.start_app(self.package)
        return self.pull_latest_pcap(device)

    def pull_latest_pcap(self, device: EmulatorDevice) -> Path | None:
        remote = self._latest_remote_pcap(device)
        if not remote:
            LOG.warning("[%s] No remote pcap file found", device.id)
            return None
        local = self.data_dir / "pcap" / f"{datetime.now():%Y%m%d}" / device.id / Path(remote).name
        device.adb.pull(remote, local)
        LOG.info("[%s] Pulled pcap: %s", device.id, local)
        return local

    def _latest_remote_pcap(self, device: EmulatorDevice) -> str:
        command = (
            "for d in /sdcard/Download /sdcard/Documents /sdcard/PCAPdroid; do "
            "if [ -d \"$d\" ]; then find \"$d\" -type f \\( -name '*.pcap' -o -name '*.pcapng' \\) 2>/dev/null; fi; "
            "done | sort | tail -n 1"
        )
        return device.adb.shell(command, timeout=20).strip()
