from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AccountConfig:
    """One business account logged into a device."""

    name: str
    account_id: str = ""
    enabled: bool = True
    created: str = ""
    rule: str = "default_rule"


@dataclass(frozen=True)
class DeviceConfig:
    """A physical or virtual Android device and its available accounts."""

    name: str
    serial: str = ""
    enabled: bool = True
    accounts: dict[str, AccountConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskConfig:
    """Endpoint and identifier metadata for one task type."""

    name: str
    enabled: bool = True
    claim_url: str = ""
    task_key: str = ""
    query_url: str = ""


@dataclass(frozen=True)
class RuleConfig:
    """Execution limits shared by one or more account tasks."""

    name: str
    enabled: bool = True
    max_tasks: int = 0
    rest_min_seconds: float = 0
    rest_max_seconds: float = 0


@dataclass(frozen=True)
class AppConfig:
    """Fully parsed application configuration."""

    version: int
    sdk_path: str
    devices: list[DeviceConfig]
    tasks: dict[str, TaskConfig]
    rules: dict[str, RuleConfig]
