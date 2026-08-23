from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised on minimal installs
    yaml = None

from .models import (
    AppConfig,
    AppRuntimeConfig,
    InstanceConfig,
    LdConfig,
    RuleConfig,
    SystemConfig,
    TaskConfig,
    XcConfig,
)


class ConfigError(ValueError):
    """Raised when the YAML config is missing required fields."""


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_config_path(project_root: Path | None = None) -> Path:
    root = project_root or default_project_root()
    config_path = root / "configs" / "config.yaml"
    if config_path.exists():
        return config_path
    return root / "configs" / "config.example.yaml"


def load_config(path: str | Path | None = None) -> AppRuntimeConfig:
    project_root = default_project_root()
    config_path = Path(path) if path else default_config_path(project_root)
    if not config_path.is_absolute():
        if config_path.exists():
            config_path = config_path.resolve()
        else:
            config_path = project_root / config_path
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    raw = _load_yaml(config_path)

    system = _parse_system(raw.get("system") or {}, project_root)
    ld = _parse_ld(raw.get("ld") or {})
    xc = _parse_xc(raw)
    return AppRuntimeConfig(
        system=system,
        ld=ld,
        xc=xc,
        config_path=config_path,
        project_root=project_root,
    )


def _parse_system(raw: dict[str, Any], project_root: Path) -> SystemConfig:
    data_dir = Path(str(raw.get("data_dir", "data")))
    if not data_dir.is_absolute():
        data_dir = project_root / data_dir
    return SystemConfig(
        exit_wait_seconds=int(raw.get("exit_wait_seconds", 20)),
        startup_wait_seconds=int(raw.get("startup_wait_seconds", 60)),
        log_level=str(raw.get("log_level", "INFO")),
        data_dir=data_dir,
        app_mode=str(raw.get("app_mode", "console")),
    )


def _parse_ld(raw: dict[str, Any]) -> LdConfig:
    instances = [_parse_instance(item) for item in raw.get("instances") or []]
    if not instances:
        raise ConfigError("ld.instances must contain at least one emulator")

    return LdConfig(
        ldplayer_path=str(raw.get("ldplayer_path", "")),
        multiplayer_path=str(raw.get("multiplayer_path", "")),
        ldconsole_path=str(raw.get("ldconsole_path", "")),
        adb_path=str(raw.get("adb_path", "")),
        instances=instances,
        wait_device_ready_seconds=int(raw.get("wait_device_ready_seconds", 90)),
        wait_app_ready_seconds=int(raw.get("wait_app_ready_seconds", 15)),
        diagnostic_running_wait_seconds=int(raw.get("diagnostic_running_wait_seconds", 60)),
        diagnostic_adb_wait_seconds=int(raw.get("diagnostic_adb_wait_seconds", 15)),
    )


def _parse_instance(item: dict[str, Any]) -> InstanceConfig:
    launch_by = str(item.get("launch_by", "index"))
    if launch_by not in ("index", "name"):
        raise ConfigError("ld.instances[].launch_by must be index or name")
    return InstanceConfig(
        id=str(item["id"]),
        name=str(item.get("name") or item["id"]),
        index=int(item["index"]),
        launch_by=launch_by,
        adb_serial=str(item.get("adb_serial", "")),
    )


def _parse_xc(raw: dict[str, Any]) -> XcConfig:
    xc_raw = raw.get("xc") or {}
    task_raw = xc_raw.get("task") or raw.get("task") or {}
    rules_raw = xc_raw.get("rule") or xc_raw.get("rules") or raw.get("strategy") or []

    app = AppConfig(packages=dict((xc_raw.get("app") or {}).get("packages") or {}))
    if not app.ctrip_package or not app.pcapdroid_package:
        raise ConfigError("xc.app.packages must define ctrip and pcapdroid")

    task = TaskConfig(
        site_name=str(_required(task_raw, "site_name")),
        base_url=str(_env_override("CTRIP_LDAUTO_BASE_URL", _required(task_raw, "base_url"))),
        username=str(_env_override("CTRIP_LDAUTO_USERNAME", _required(task_raw, "username"))),
        password=str(_env_override("CTRIP_LDAUTO_PASSWORD", _required(task_raw, "password"))),
        login_path=str(_required(task_raw, "login_path")),
        city_path=str(_required(task_raw, "city_path")),
        task_path=str(_required(task_raw, "task_path")),
        receive_task_path=str(_required(task_raw, "receive_task_path")),
        upload_pcap_path=str(_required(task_raw, "upload_pcap_path")),
        request_timeout_seconds=int(task_raw.get("request_timeout_seconds", 20)),
    )

    if isinstance(rules_raw, dict):
        rules_raw = [rules_raw]
    rules = [
        RuleConfig(
            name=str(item.get("name") or f"rule-{idx + 1}"),
            batch_rest_seconds=int(item.get("batch_rest_seconds", 300)),
            task_rest_seconds=int(item.get("task_rest_seconds", 30)),
            browse_seconds=int(item.get("browse_seconds", 20)),
            empty_task_retry_seconds=int(item.get("empty_task_retry_seconds", 60)),
            max_task_retry=int(item.get("max_task_retry", 3)),
            instance_ids=[str(value) for value in item.get("instance_ids") or []],
        )
        for idx, item in enumerate(rules_raw or [])
    ]
    if not rules:
        raise ConfigError("xc.rule must contain at least one rule")

    return XcConfig(app=app, task=task, rules=rules)


def _required(raw: dict[str, Any], key: str) -> Any:
    value = raw.get(key)
    if value in (None, ""):
        raise ConfigError(f"Missing required config: {key}")
    return value


def _env_override(name: str, fallback: Any) -> Any:
    return os.environ.get(name) or fallback


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text) or {}
    parsed = _parse_simple_yaml(text)
    if not isinstance(parsed, dict):
        raise ConfigError(f"Config root must be a mapping: {path}")
    return parsed


def _parse_simple_yaml(text: str) -> Any:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        lines.append((len(line) - len(line.lstrip(" ")), line.strip()))

    def parse_block(pos: int, indent: int) -> tuple[Any, int]:
        if pos >= len(lines):
            return {}, pos
        if lines[pos][1].startswith("- "):
            return parse_list(pos, indent)
        return parse_mapping(pos, indent)

    def parse_mapping(pos: int, indent: int) -> tuple[dict[str, Any], int]:
        result: dict[str, Any] = {}
        while pos < len(lines):
            line_indent, content = lines[pos]
            if line_indent < indent:
                break
            if line_indent > indent:
                break
            if content.startswith("- "):
                break
            key, value = _split_key_value(content)
            pos += 1
            if value == "":
                if pos < len(lines) and lines[pos][0] > line_indent:
                    result[key], pos = parse_block(pos, lines[pos][0])
                else:
                    result[key] = {}
            else:
                result[key] = _parse_scalar(value)
        return result, pos

    def parse_list(pos: int, indent: int) -> tuple[list[Any], int]:
        result: list[Any] = []
        while pos < len(lines):
            line_indent, content = lines[pos]
            if line_indent < indent:
                break
            if line_indent != indent or not content.startswith("- "):
                break
            item_text = content[2:].strip()
            pos += 1
            if item_text == "":
                if pos < len(lines) and lines[pos][0] > line_indent:
                    item, pos = parse_block(pos, lines[pos][0])
                else:
                    item = None
                result.append(item)
                continue
            if ":" in item_text:
                key, value = _split_key_value(item_text)
                item_dict: dict[str, Any] = {key: _parse_scalar(value) if value else {}}
                if value == "" and pos < len(lines) and lines[pos][0] > line_indent:
                    item_dict[key], pos = parse_block(pos, lines[pos][0])
                if pos < len(lines) and lines[pos][0] > line_indent:
                    extra, pos = parse_mapping(pos, lines[pos][0])
                    item_dict.update(extra)
                result.append(item_dict)
            else:
                result.append(_parse_scalar(item_text))
        return result, pos

    parsed, final_pos = parse_block(0, lines[0][0] if lines else 0)
    if final_pos != len(lines):
        raise ConfigError("Unsupported YAML structure; install PyYAML for full YAML support")
    return parsed


def _split_key_value(content: str) -> tuple[str, str]:
    if ":" not in content:
        raise ConfigError(f"Invalid YAML line: {content}")
    key, value = content.split(":", 1)
    return key.strip(), value.strip()


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "none", "~"):
        return None
    try:
        return int(value)
    except ValueError:
        return value
