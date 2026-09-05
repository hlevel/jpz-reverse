"""Device discovery and one-session-per-device management."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from layernav_android.adb import SubprocessAdb
from layernav_android.config.models import AppConfig, DeviceConfig


class DeviceManager:
    """Create ADB sessions for enabled devices and filter offline devices."""

    def __init__(self, config: AppConfig, factory: Callable[[DeviceConfig], SubprocessAdb] | None = None) -> None:
        self.config = config
        if factory is not None:
            self.factory = factory
        else:
            adb_bin = str(Path(config.sdk_path) / "platform-tools" / "adb.exe") if config.sdk_path else "adb"
            self.factory = lambda device: SubprocessAdb(device.serial, adb_bin=adb_bin)

    def sessions(self) -> Iterator[tuple[DeviceConfig, SubprocessAdb]]:
        """Yield one connected ADB session per enabled and online device."""
        for device in self.config.devices:
            if not device.enabled:
                continue
            adb = self.factory(device)
            try:
                adb._run(["get-state"])
                wake = getattr(adb, "wake_and_unlock", None)
                if callable(wake):
                    wake()
            except Exception:
                continue
            yield device, adb
