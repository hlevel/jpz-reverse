from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from layernav_android.config.models import (
    AccountConfig, AppConfig, DeviceConfig, RuleConfig, TaskConfig,
)


class ConfigError(ValueError):
    """Raised when the application configuration is invalid."""


def load_config(path: str | Path) -> AppConfig:
    """Load and validate a YAML configuration file.

    Account keys intentionally match task keys, so no second mapping table is
    needed: ``accounts.ctrip_mini_program`` resolves to
    ``tasks.ctrip_mini_program``.
    """
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {source}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML: {source}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("top-level config must be a mapping")
    devices = _parse_devices(raw.get("devices"))
    tasks = _parse_tasks(raw.get("tasks"))
    rules = _parse_rules(raw.get("rules"))

    for device in devices:
        for account_name, account in device.accounts.items():
            if account_name not in tasks:
                raise ConfigError(
                    f"device {device.name!r} account {account_name!r} "
                    "has no same-name task definition"
                )
            if account.rule not in rules:
                raise ConfigError(
                    f"device {device.name!r} account {account_name!r} "
                    f"references unknown rule {account.rule!r}"
                )
    return AppConfig(int(raw.get("version", 1)), str(raw.get("sdk_path", "")), devices, tasks, rules)


def _parse_devices(value: Any) -> list[DeviceConfig]:
    """Convert the raw ``devices`` list into typed device objects."""
    if not isinstance(value, list):
        raise ConfigError("devices must be a list")
    result: list[DeviceConfig] = []
    for item in value:
        if not isinstance(item, dict) or not item.get("name"):
            raise ConfigError("each device requires a name")
        accounts_raw = item.get("accounts", {})
        if not isinstance(accounts_raw, dict):
            raise ConfigError(f"device {item['name']!r}: accounts must be a mapping")
        accounts = {
            name: AccountConfig(name=name, **_account_fields(data))
            for name, data in accounts_raw.items()
        }
        result.append(DeviceConfig(
            name=str(item["name"]), serial=str(item.get("serial", "")),
            enabled=bool(item.get("enabled", True)), accounts=accounts,
        ))
    return result


def _account_fields(value: Any) -> dict[str, Any]:
    """Extract only supported account fields and reject scalar values."""
    if not isinstance(value, dict):
        raise ConfigError("account config must be a mapping")
    return {key: value[key] for key in ("account_id", "enabled", "created", "rule") if key in value}


def _parse_tasks(value: Any) -> dict[str, TaskConfig]:
    """Convert the top-level task mapping into typed task objects."""
    if not isinstance(value, dict):
        raise ConfigError("tasks must be a mapping")
    result = {}
    for name, data in value.items():
        if not isinstance(data, dict):
            raise ConfigError(f"task {name!r} must be a mapping")
        result[str(name)] = TaskConfig(name=str(name), **{
            key: data[key] for key in ("enabled", "claim_url", "task_key", "query_url") if key in data
        })
    return result


def _parse_rules(value: Any) -> dict[str, RuleConfig]:
    """Convert the rule list and validate numeric limits and uniqueness."""
    if not isinstance(value, list):
        raise ConfigError("rules must be a list")
    result = {}
    for data in value:
        if not isinstance(data, dict) or not data.get("name"):
            raise ConfigError("each rule requires a name")
        rest = data.get("rest_interval_seconds", {})
        if not isinstance(rest, dict):
            raise ConfigError(f"rule {data['name']!r}: rest interval must be a mapping")
        rule = RuleConfig(
            name=str(data["name"]), enabled=bool(data.get("enabled", True)),
            max_tasks=int(data.get("max_tasks", 0)),
            rest_min_seconds=float(rest.get("min", 0)),
            rest_max_seconds=float(rest.get("max", 0)),
        )
        if rule.name in result:
            raise ConfigError(f"duplicate rule: {rule.name!r}")
        if rule.max_tasks < 0 or rule.rest_min_seconds < 0 or rule.rest_max_seconds < rule.rest_min_seconds:
            raise ConfigError(f"invalid limits in rule {rule.name!r}")
        result[rule.name] = rule
    return result
