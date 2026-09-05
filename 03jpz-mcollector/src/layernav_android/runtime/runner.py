from __future__ import annotations

import random
import time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from layernav_android._protocol import AdbProtocol
from layernav_android.base import BaseLayerModel
from layernav_android.config.models import AccountConfig, AppConfig, DeviceConfig, RuleConfig, TaskConfig


@dataclass(frozen=True)
class TaskContext:
    """All configuration required to run one account on one device."""

    device: DeviceConfig
    account: AccountConfig
    task: TaskConfig
    rule: RuleConfig


ModelFactory = Callable[[TaskContext], BaseLayerModel]
AdbFactory = Callable[[DeviceConfig], AdbProtocol]


class TaskRunner:
    """Orchestrate configured devices while delegating UI work to layer models.

    The runner owns scheduling and counters only.  Screen recognition,
    navigation and business actions remain in the injected layer model.
    """

    def __init__(self, config: AppConfig, adb_factory: AdbFactory, model_factory: ModelFactory) -> None:
        self.config = config
        self.adb_factory = adb_factory
        self.model_factory = model_factory

    def contexts(self) -> list[TaskContext]:
        """Build runnable contexts from enabled device/account/task/rule entries."""
        result: list[TaskContext] = []
        for device in self.config.devices:
            if not device.enabled:
                continue
            for account_name, account in device.accounts.items():
                task = self.config.tasks[account_name]
                rule = self.config.rules[account.rule]
                if account.enabled and task.enabled and rule.enabled:
                    result.append(TaskContext(device, account, task, rule))
        return result

    def run_once(self, context: TaskContext) -> int:
        """Run one configured account until its rule limit; returns completed count.

        Concrete models implement claim/collect/query in ``run_task``.  The
        default model hook keeps this framework runnable before UI details exist.
        """
        # A fresh client/model pair isolates one device-account execution.
        adb = self.adb_factory(context.device)
        model = self.model_factory(context)
        model.init(adb)
        completed = 0
        # max_tasks=0 means unlimited execution; a model decides when no task remains.
        while context.rule.max_tasks == 0 or completed < context.rule.max_tasks:
            run_task = getattr(model, "run_task", None)
            if run_task is None or not run_task(adb, context.task):
                break
            completed += 1
            # Rest only happens between successful tasks, not after the limit.
            has_more = context.rule.max_tasks == 0 or completed < context.rule.max_tasks
            if has_more and context.rule.rest_max_seconds > 0:
                time.sleep(random.uniform(context.rule.rest_min_seconds, context.rule.rest_max_seconds))
        return completed

    def run_device(self, device: DeviceConfig, adb: AdbProtocol | None = None) -> dict[str, int]:
        """Run all runnable accounts on one device serially.

        A device owns one control channel, so its accounts must never be
        operated by separate threads at the same time.
        """
        device_results: dict[str, int] = {}
        # The caller normally supplies the single session owned by this worker.
        # The fallback keeps this method convenient for direct unit use.
        device_adb = adb
        for context in self.contexts():
            if context.device.name != device.name:
                continue
            key = f"{device.name}:{context.account.name}"
            if device_adb is None:
                device_results[key] = self.run_once(context)
                continue
            model = self.model_factory(context)
            model.init(device_adb)
            completed = 0
            while context.rule.max_tasks == 0 or completed < context.rule.max_tasks:
                run_task = getattr(model, "run_task", None)
                if run_task is None or not run_task(device_adb, context.task):
                    break
                completed += 1
                if (context.rule.max_tasks == 0 or completed < context.rule.max_tasks) and context.rule.rest_max_seconds > 0:
                    time.sleep(random.uniform(context.rule.rest_min_seconds, context.rule.rest_max_seconds))
            device_results[key] = completed
        return device_results

    def run_all(self, *, max_workers: int | None = None) -> dict[str, int]:
        """Run runnable contexts concurrently and return completion counts.

        Each device gets one worker; accounts on that device run serially.
        This keeps ADB sessions isolated and makes the method safe for
        multi-device collection. Exceptions are re-raised after the future
        completes so callers can apply their preferred retry policy.
        """
        devices = [device for device in self.config.devices if device.enabled]
        if not devices:
            return {}
        # One worker per device by default; accounts on one device stay serial.
        workers = max_workers or len(devices)
        if workers < 1:
            raise ValueError("max_workers must be at least 1")
        results: dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=min(workers, len(devices))) as pool:
            futures = {
                pool.submit(self.run_device, device, self.adb_factory(device)): device
                for device in devices
            }
            for future in as_completed(futures):
                results.update(future.result())
        return results
