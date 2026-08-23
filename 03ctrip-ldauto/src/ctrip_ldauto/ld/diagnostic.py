from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ctrip_ldauto.config import AppConfig, InstanceConfig, LdConfig

from .adb import AdbDevice
from .ldconsole import LDConsoleClient, LDConsoleError

LOG = logging.getLogger(__name__)


@dataclass
class InstanceDiagnostic:
    instance_id: str
    index: int
    configured_name: str
    actual_name: str = ""
    exists: bool = False
    name_matches: bool = False
    running_before: bool = False
    running_after_launch: bool = False
    started_by_check: bool = False
    serial: str = ""
    adb_ready: bool = False
    ctrip_installed: bool | None = None
    pcapdroid_installed: bool | None = None
    suggestions: list[str] = field(default_factory=list)
    error: str = ""


def check_ld_instances(
    ld_config: LdConfig,
    app_config: AppConfig,
    *,
    start: bool = True,
    close_started: bool = True,
    running_wait_seconds: int = 20,
    adb_wait_seconds: int | None = None,
) -> list[InstanceDiagnostic]:
    client = LDConsoleClient(ld_config)
    adb_path = client.adb_path(ld_config.adb_path)
    actual_by_index = {int(item["index"]): item for item in client.list_instances_detailed()}
    results: list[InstanceDiagnostic] = []

    for instance in ld_config.instances:
        diag = InstanceDiagnostic(
            instance_id=instance.id,
            index=instance.index,
            configured_name=instance.name,
        )
        results.append(diag)
        actual = actual_by_index.get(instance.index)
        if not actual:
            diag.suggestions.append(f"Set index to one of: {sorted(actual_by_index)}")
            diag.error = "Configured index does not exist in LDPlayer list2"
            continue

        diag.exists = True
        diag.actual_name = str(actual.get("name") or "")
        diag.name_matches = diag.actual_name == instance.name
        if instance.launch_by == "name" and not diag.name_matches:
            diag.suggestions.append("launch_by=name requires exact instance name; use launch_by=index.")

        try:
            diag.running_before = client.is_running_instance(instance)
            if start and not diag.running_before:
                client.launch_instance(instance)
                diag.started_by_check = True
                diag.running_after_launch = _wait_running(client, instance, running_wait_seconds)
            else:
                diag.running_after_launch = diag.running_before

            if not diag.running_after_launch:
                diag.suggestions.append("Instance is not running; enable start or start it manually before ADB checks.")
                continue

            diag.serial = client.serial_instance(instance)
            adb = AdbDevice(adb_path, diag.serial)
            diag.adb_ready = adb.wait_ready(
                adb_wait_seconds if adb_wait_seconds is not None else ld_config.wait_device_ready_seconds
            )
            if not diag.adb_ready:
                diag.suggestions.append(
                    "ADB is not ready. If this emulator uses a nonstandard port, set adb_serial."
                )
                continue

            diag.ctrip_installed = adb.is_package_installed(app_config.ctrip_package)
            diag.pcapdroid_installed = adb.is_package_installed(app_config.pcapdroid_package)
            if not diag.ctrip_installed:
                diag.suggestions.append(f"Install Ctrip package: {app_config.ctrip_package}")
            if not diag.pcapdroid_installed:
                diag.suggestions.append(f"Install PCAPdroid package: {app_config.pcapdroid_package}")
        except Exception as exc:
            LOG.exception("LD diagnostic failed for %s", instance.id)
            diag.error = str(exc)
        finally:
            if close_started and diag.started_by_check:
                try:
                    client.quit_instance(instance)
                except LDConsoleError as exc:
                    diag.suggestions.append(f"Manual cleanup may be needed: {exc}")

    return results


def _wait_running(client: LDConsoleClient, instance: InstanceConfig, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if client.is_running_instance(instance):
            return True
        time.sleep(1)
    return client.is_running_instance(instance)
