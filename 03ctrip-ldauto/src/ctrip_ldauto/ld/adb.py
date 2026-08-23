from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path

LOG = logging.getLogger(__name__)


class AdbError(RuntimeError):
    pass


class AdbDevice:
    def __init__(self, adb_path: Path, serial: str) -> None:
        self.adb_path = adb_path
        self.serial = serial

    def run(self, *args: str, timeout: int = 10, retries: int = 3) -> str:
        cmd = [str(self.adb_path), "-s", self.serial, *args]
        last_error = ""
        for attempt in range(1, retries + 1):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired:
                last_error = f"timeout after {timeout}s"
            else:
                if result.returncode == 0:
                    return result.stdout.strip()
                last_error = result.stderr.strip()
            if attempt < retries:
                time.sleep(0.5)
        raise AdbError(f"ADB failed: {' '.join(cmd)}; {last_error}")

    def ok(self) -> bool:
        try:
            return "ok" in self.run("shell", "echo", "ok", timeout=3, retries=1).lower()
        except AdbError:
            return False

    def wait_ready(self, seconds: int) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.ok():
                return True
            time.sleep(1)
        return False

    def tap(self, x: int, y: int) -> None:
        self.run("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.run(
            "shell",
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
        )

    def input_text(self, text: str) -> None:
        escaped = text.replace(" ", "%s").replace('"', '\\"')
        self.run("shell", "input", "text", escaped)

    def keyevent(self, code: int) -> None:
        self.run("shell", "input", "keyevent", str(code))

    def back(self) -> None:
        self.keyevent(4)

    def home(self) -> None:
        self.keyevent(3)

    def start_app(self, package: str) -> None:
        self.run(
            "shell",
            "monkey",
            "-p",
            package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
            timeout=15,
        )

    def stop_app(self, package: str) -> None:
        self.run("shell", "am", "force-stop", package)

    def is_package_installed(self, package: str) -> bool:
        try:
            self.run("shell", "pm", "path", package)
            return True
        except AdbError:
            return False

    def foreground_package(self) -> str:
        output = self.run("shell", "dumpsys", "activity", "activities", timeout=10)
        match = re.search(r"mResumedActivity.*? ([^/\s]+)/", output)
        return match.group(1) if match else ""

    def screenshot(self) -> bytes:
        cmd = [str(self.adb_path), "-s", self.serial, "exec-out", "screencap", "-p"]
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise AdbError(f"screenshot failed: {stderr}")
        return result.stdout

    def shell(self, command: str, timeout: int = 10) -> str:
        return self.run("shell", command, timeout=timeout)

    def pull(self, remote: str, local: Path, timeout: int = 60) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        self.run("pull", remote, str(local), timeout=timeout, retries=1)
