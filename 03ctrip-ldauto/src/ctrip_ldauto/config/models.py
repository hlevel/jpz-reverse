from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SystemConfig:
    exit_wait_seconds: int = 20
    startup_wait_seconds: int = 60
    log_level: str = "INFO"
    data_dir: Path = Path("data")
    app_mode: str = "console"


@dataclass(frozen=True)
class InstanceConfig:
    id: str
    name: str
    index: int
    launch_by: str = "index"
    adb_serial: str = ""


@dataclass(frozen=True)
class LdConfig:
    ldplayer_path: str = ""
    multiplayer_path: str = ""
    ldconsole_path: str = ""
    adb_path: str = ""
    instances: list[InstanceConfig] = field(default_factory=list)
    wait_device_ready_seconds: int = 90
    wait_app_ready_seconds: int = 15
    diagnostic_running_wait_seconds: int = 60
    diagnostic_adb_wait_seconds: int = 15


@dataclass(frozen=True)
class AppConfig:
    packages: dict[str, str] = field(default_factory=dict)

    @property
    def ctrip_package(self) -> str:
        return self.packages.get("ctrip", "")

    @property
    def pcapdroid_package(self) -> str:
        return self.packages.get("pcapdroid", "")


@dataclass(frozen=True)
class TaskConfig:
    site_name: str
    base_url: str
    username: str
    password: str
    login_path: str
    city_path: str
    task_path: str
    receive_task_path: str
    upload_pcap_path: str
    request_timeout_seconds: int = 20


@dataclass(frozen=True)
class RuleConfig:
    name: str
    batch_rest_seconds: int = 300
    task_rest_seconds: int = 30
    browse_seconds: int = 20
    empty_task_retry_seconds: int = 60
    max_task_retry: int = 3
    instance_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class XcConfig:
    app: AppConfig
    task: TaskConfig
    rules: list[RuleConfig]


@dataclass(frozen=True)
class AppRuntimeConfig:
    system: SystemConfig
    ld: LdConfig
    xc: XcConfig
    config_path: Path
    project_root: Path
