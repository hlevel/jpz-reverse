from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class TaskStorage:
    def __init__(self, data_dir: Path, site_name: str) -> None:
        self.site_dir = data_dir / site_name
        self.site_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def cookie_path(self, emulator_id: str) -> Path:
        return self.site_dir / f"ck_{self._today()}_{emulator_id}.txt"

    def task_path(self, emulator_id: str) -> Path:
        return self.site_dir / f"task_{self._today()}_{emulator_id}.txt"

    def write_cookie(self, emulator_id: str, cookie: str) -> None:
        self.cookie_path(emulator_id).write_text(cookie, encoding="utf-8")

    def append_tasks(self, emulator_id: str, tasks: list[dict[str, Any]]) -> None:
        if not tasks:
            return
        with self._lock:
            existing = self.read_tasks(emulator_id)
            seen = {str(item.get("id") or item.get("task_id") or item.get("_local_id")) for item in existing}
            with self.task_path(emulator_id).open("a", encoding="utf-8") as fh:
                for idx, task in enumerate(tasks):
                    local_id = str(task.get("id") or task.get("task_id") or f"{datetime.now():%H%M%S%f}_{idx}")
                    if local_id in seen:
                        continue
                    record = {
                        "_local_id": local_id,
                        "status": "new",
                        "retry": 0,
                        "task": task,
                    }
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_tasks(self, emulator_id: str) -> list[dict[str, Any]]:
        path = self.task_path(emulator_id)
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    def claim_next(self, emulator_id: str) -> dict[str, Any] | None:
        with self._lock:
            records = self.read_tasks(emulator_id)
            for record in records:
                if record.get("status") == "new":
                    record["status"] = "claimed"
                    self._write_records(emulator_id, records)
                    return record
        return None

    def update_status(
        self,
        emulator_id: str,
        local_id: str,
        status: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            records = self.read_tasks(emulator_id)
            for record in records:
                if str(record.get("_local_id")) == str(local_id):
                    record["status"] = status
                    if extra:
                        record.update(extra)
                    break
            self._write_records(emulator_id, records)

    def _write_records(self, emulator_id: str, records: list[dict[str, Any]]) -> None:
        path = self.task_path(emulator_id)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        tmp.replace(path)

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y%m%d")
