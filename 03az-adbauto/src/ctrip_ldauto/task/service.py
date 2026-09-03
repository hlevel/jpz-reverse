from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ctrip_ldauto.config import TaskConfig

from .client import TaskApiClient
from .storage import TaskStorage

LOG = logging.getLogger(__name__)


class TaskService:
    def __init__(self, config: TaskConfig, data_dir: Path) -> None:
        self.config = config
        self.client = TaskApiClient(config)
        self.storage = TaskStorage(data_dir, config.site_name)

    def bootstrap_instance(self, emulator_id: str) -> int:
        cookie = self.client.login()
        self.storage.write_cookie(emulator_id, cookie)

        cities = self.client.fetch_cities()
        city = cities[0] if cities else None
        tasks = self.client.fetch_tasks(city)
        self.storage.append_tasks(emulator_id, tasks)
        LOG.info("Bootstrapped %d task(s) for %s", len(tasks), emulator_id)
        return len(tasks)

    def claim_or_receive(self, emulator_id: str) -> dict[str, Any] | None:
        record = self.storage.claim_next(emulator_id)
        if record:
            return record

        task = self.client.receive_task(emulator_id)
        if task:
            self.storage.append_tasks(emulator_id, [task])
            return self.storage.claim_next(emulator_id)
        return None

    def mark(self, emulator_id: str, local_id: str, status: str, **extra: Any) -> None:
        self.storage.update_status(emulator_id, local_id, status, extra or None)

    def upload_pcap(self, emulator_id: str, record: dict[str, Any], pcap_path: Path) -> None:
        task = record.get("task") or {}
        task_id = str(task.get("id") or task.get("task_id") or record.get("_local_id"))
        result = self.client.upload_pcap(task_id, emulator_id, pcap_path)
        self.mark(
            emulator_id,
            str(record["_local_id"]),
            "uploaded",
            upload_result=result,
            pcap_path=str(pcap_path),
        )
