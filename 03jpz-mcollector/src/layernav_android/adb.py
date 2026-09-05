"""Subprocess based ADB client used by the runtime device manager."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


class AdbError(RuntimeError):
    """Raised when an ADB command fails."""


@dataclass(frozen=True)
class DeviceInfo:
    """Basic device metadata used to validate screenshot dimensions."""

    serial: str
    state: str
    width: int = 0
    height: int = 0
    model: str = ""

    @property
    def online(self) -> bool:
        return self.state == "device"


class SubprocessAdb:
    """Small, synchronous ADB adapter implementing :class:`AdbProtocol`."""

    def __init__(self, serial: str = "", adb_bin: str = "adb") -> None:
        self.serial = serial
        self.adb_bin = adb_bin

    def _run(self, args: list[str]) -> str:
        command = [self.adb_bin, "-s", self.serial, *args] if self.serial else [self.adb_bin, *args]
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode:
            error = result.stderr.decode(errors="replace").strip()
            raise AdbError(f"ADB command failed ({result.returncode}): {error}")
        return result.stdout.decode(errors="replace")

    def screencap(self) -> bytes:
        command = [self.adb_bin, "-s", self.serial, "exec-out", "screencap", "-p"] if self.serial else [self.adb_bin, "exec-out", "screencap", "-p"]
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode:
            raise AdbError(result.stderr.decode(errors="replace"))
        return result.stdout

    def device_info(self) -> DeviceInfo:
        """Read online state, physical resolution and model information."""
        state = self._run(["get-state"]).strip()
        size = self._run(["shell", "wm", "size"])
        match = re.search(r"(\d+)\s*x\s*(\d+)", size)
        width, height = (int(match.group(1)), int(match.group(2))) if match else (0, 0)
        model = self._run(["shell", "getprop", "ro.product.model"]).strip()
        return DeviceInfo(self.serial, state, width, height, model)

    def capture_png(self) -> bytes:
        """Capture a validated PNG frame from the device."""
        data = self.screencap()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise AdbError("ADB screenshot is not a PNG")
        if cv2 is not None:
            image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None or image.size == 0:
                raise AdbError("ADB screenshot cannot be decoded")
        return data

    def key_event(self, code: int) -> None:
        self._run(["shell", "input", "keyevent", str(code)])

    def is_locked(self) -> bool:
        """Return whether Android currently reports an active keyguard."""
        output = self._run(["shell", "dumpsys", "window", "policy"])
        return bool(re.search(r"(?:isStatusBarKeyguard|showing)=true", output, re.IGNORECASE))

    def wake_and_unlock(self) -> bool:
        """Wake and dismiss an unsecured lock screen without entering credentials.

        This intentionally cannot bypass PIN, password, fingerprint or pattern
        protection. On an unlocked device it is a no-op apart from a wake event.
        """
        self.key_event(224)  # KEYCODE_WAKEUP
        try:
            # Works on many AOSP-derived ROMs; failure is non-fatal.
            self._run(["shell", "wm", "dismiss-keyguard"])
        except AdbError:
            pass
        # MIUI commonly needs an explicit upward swipe after the wake event.
        self.swipe(540, 1800, 540, 450, duration_ms=350)
        return not self.is_locked()

    def tap(self, x: int, y: int) -> None:
        self._run(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._run(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])

    def foreground_package(self) -> str:
        """Return the resumed package, accommodating MIUI and AOSP formats."""
        activity_output = self._run(["shell", "dumpsys", "activity", "activities"])
        # Most Android versions report the active app here, including MIUI.
        match = re.search(r"mResumedActivity:.*?\s([\w.]+)/", activity_output)
        if match:
            return match.group(1)

        # Older builds may expose only a focused window record.
        window_output = self._run(["shell", "dumpsys", "window", "windows"])
        match = re.search(r"(?:mCurrentFocus|mFocusedApp).*?\s([\w.]+)/", window_output)
        return match.group(1) if match else ""
