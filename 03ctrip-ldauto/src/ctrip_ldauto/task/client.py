from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from ctrip_ldauto.config import TaskConfig

LOG = logging.getLogger(__name__)


class TaskApiError(RuntimeError):
    pass


class TaskApiClient:
    def __init__(self, config: TaskConfig) -> None:
        self.config = config
        try:
            import requests
        except ModuleNotFoundError as exc:
            raise TaskApiError(
                "Missing dependency: requests. Run `python -m pip install -r requirements.txt`."
            ) from exc
        self.session = requests.Session()

    def login(self) -> str:
        url = self._url(self.config.login_path)
        response = self.session.post(
            url,
            json={"username": self.config.username, "password": self.config.password},
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        cookie = self._cookie_header()
        LOG.info("Task site login succeeded: %s", self.config.site_name)
        return cookie

    def fetch_cities(self) -> list[dict[str, Any]]:
        data = self._get_json(self.config.city_path)
        return self._extract_list(data, "cities", "data", "items")

    def fetch_tasks(self, city: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        params = {}
        if city:
            city_id = city.get("id") or city.get("city_id") or city.get("code")
            if city_id is not None:
                params["city_id"] = city_id
        data = self._get_json(self.config.task_path, params=params)
        return self._extract_list(data, "tasks", "data", "items")

    def receive_task(self, emulator_id: str) -> dict[str, Any] | None:
        response = self.session.post(
            self._url(self.config.receive_task_path),
            json={"emulator_id": emulator_id},
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            task = data.get("task") or data.get("data")
            if isinstance(task, dict):
                return task
        return data if isinstance(data, dict) else None

    def upload_pcap(self, task_id: str, emulator_id: str, path: Path) -> dict[str, Any]:
        with path.open("rb") as fh:
            response = self.session.post(
                self._url(self.config.upload_pcap_path),
                data={"task_id": task_id, "emulator_id": emulator_id},
                files={"file": (path.name, fh, "application/vnd.tcpdump.pcap")},
                timeout=max(self.config.request_timeout_seconds, 60),
            )
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            return {"ok": True, "text": response.text}

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(
            self._url(path),
            params=params,
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def _url(self, path: str) -> str:
        return urljoin(self.config.base_url.rstrip("/") + "/", path.lstrip("/"))

    def _cookie_header(self) -> str:
        return "; ".join(f"{cookie.name}={cookie.value}" for cookie in self.session.cookies)

    @staticmethod
    def _extract_list(data: Any, *keys: str) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in keys:
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
                if isinstance(value, dict):
                    nested = TaskApiClient._extract_list(value, *keys)
                    if nested:
                        return nested
        return []
