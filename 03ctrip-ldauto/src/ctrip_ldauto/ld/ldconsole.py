from __future__ import annotations

import logging
import locale
import os
import subprocess
from pathlib import Path

from ctrip_ldauto.config import InstanceConfig, LdConfig

LOG = logging.getLogger(__name__)


class LDConsoleError(RuntimeError):
    pass


class LDConsoleClient:
    def __init__(self, config: LdConfig) -> None:
        self.ldplayer_path = Path(config.ldplayer_path) if config.ldplayer_path else None
        self.multiplayer_path = (
            Path(config.multiplayer_path) if config.multiplayer_path else None
        )
        self.ldconsole_path = self._resolve_ldconsole(config)
        if self.ldplayer_path is None:
            self.ldplayer_path = self.ldconsole_path.parent

    def _resolve_ldconsole(self, config: LdConfig) -> Path:
        candidates: list[Path] = []
        if config.ldconsole_path:
            candidates.append(Path(config.ldconsole_path))
        if config.ldplayer_path:
            candidates.append(Path(config.ldplayer_path) / "ldconsole.exe")
        candidates.extend(self._ldconsole_candidates_from_multiplayer(config.multiplayer_path))
        candidates.extend(
            [
                Path("D:/leidian/LDPlayer9/ldconsole.exe"),
                Path("C:/leidian/LDPlayer9/ldconsole.exe"),
                Path("D:/LDPlayer/LDPlayer9/ldconsole.exe"),
                Path("C:/LDPlayer/LDPlayer9/ldconsole.exe"),
                Path("D:/Program Files/leidian/LDPlayer9/ldconsole.exe"),
                Path("C:/Program Files/leidian/LDPlayer9/ldconsole.exe"),
                Path("D:/Program Files/LDPlayer/LDPlayer9/ldconsole.exe"),
                Path("C:/Program Files/LDPlayer/LDPlayer9/ldconsole.exe"),
                Path("D:/Program Files/leidian/LDPlayer14/ldconsole.exe"),
                Path("C:/Program Files/leidian/LDPlayer14/ldconsole.exe"),
                Path("D:/Program Files/LDPlayer/LDPlayer14/ldconsole.exe"),
                Path("C:/Program Files/LDPlayer/LDPlayer14/ldconsole.exe"),
            ]
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        hint = ", ".join(str(item) for item in candidates)
        raise LDConsoleError(f"ldconsole.exe not found. searched: {hint}")

    def _ldconsole_candidates_from_multiplayer(self, multiplayer_path: str) -> list[Path]:
        if not multiplayer_path:
            return []
        path = Path(multiplayer_path)
        base = path.parent if path.suffix.lower() == ".exe" else path
        candidates: list[Path] = []

        pathconfig = base / "pathconfig.ini"
        if pathconfig.exists():
            players = self._read_player_paths(pathconfig)
            for key in ("player14", "player9"):
                player_path = players.get(key)
                if player_path:
                    candidates.append(Path(player_path) / "ldconsole.exe")

        parent = base.parent
        candidates.extend(
            [
                parent / "LDPlayer14" / "ldconsole.exe",
                parent / "LDPlayer9" / "ldconsole.exe",
            ]
        )
        return candidates

    @staticmethod
    def _read_player_paths(pathconfig: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in pathconfig.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("[") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip().strip('"')
            if key.startswith("player") and value:
                result[key] = value
        return result

    def run(self, *args: str, timeout: int = 15) -> str:
        cmd = [str(self.ldconsole_path), *args]
        LOG.debug("ldconsole command: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding=_ldconsole_encoding(),
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            raise LDConsoleError(f"ldconsole timeout: {' '.join(cmd)}") from exc

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise LDConsoleError(f"ldconsole failed: {' '.join(cmd)}; {stderr}")
        return result.stdout.strip()

    def list_instances(self) -> list[dict[str, str | int]]:
        output = self.run("list")
        instances: list[dict[str, str | int]] = []
        for index, line in enumerate(output.splitlines()):
            line = line.strip()
            if not line:
                continue
            if "," not in line:
                instances.append({"index": index, "name": line})
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 2 and parts[0].isdigit():
                instances.append({"index": int(parts[0]), "name": parts[1]})
        return instances

    def list_instances_detailed(self) -> list[dict[str, str | int | bool]]:
        output = self.run("list2")
        instances: list[dict[str, str | int | bool]] = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 5 or not parts[0].isdigit():
                continue
            index = int(parts[0])
            top_window = _to_int(parts[2])
            bind_window = _to_int(parts[3])
            android_started = _to_int(parts[4])
            pid = _to_int(parts[5]) if len(parts) > 5 else -1
            instances.append(
                {
                    "index": index,
                    "name": parts[1],
                    "top_window": top_window,
                    "bind_window": bind_window,
                    "android_started": android_started,
                    "pid": pid,
                    "running": android_started > 0 or pid > 0 or top_window > 0,
                }
            )
        return instances

    def is_running(self, index: int) -> bool:
        output = self.run("isrunning", "--index", str(index))
        return "running" in output.lower()

    def is_running_instance(self, instance: InstanceConfig) -> bool:
        for item in self.list_instances_detailed():
            if int(item["index"]) == instance.index:
                return bool(item["running"])
        output = self.run("isrunning", *self._target_args(instance))
        return "running" in output.lower()

    def launch(self, index: int) -> None:
        self.run("launch", "--index", str(index), timeout=30)

    def launch_instance(self, instance: InstanceConfig) -> None:
        self.run("launch", *self._target_args(instance), timeout=30)

    def quit(self, index: int) -> None:
        self.run("quit", "--index", str(index), timeout=30)

    def quit_instance(self, instance: InstanceConfig) -> None:
        self.run("quit", *self._target_args(instance), timeout=30)

    def serial(self, index: int) -> str:
        try:
            output = self.run(
                "adb",
                "--index",
                str(index),
                "--command",
                "get-serialno",
                timeout=10,
            )
            if output and "error" not in output.lower():
                return output.strip()
        except LDConsoleError:
            LOG.debug("ldconsole adb serial failed, falling back to port rule", exc_info=True)
        return f"emulator-{5554 + index * 2}"

    def serial_instance(self, instance: InstanceConfig) -> str:
        if instance.adb_serial:
            return instance.adb_serial
        try:
            output = self.run(
                "adb",
                *self._target_args(instance),
                "--command",
                "get-serialno",
                timeout=10,
            )
            if output and "error" not in output.lower():
                return output.strip()
        except LDConsoleError:
            LOG.debug("ldconsole adb serial failed, falling back to port rule", exc_info=True)
        return f"emulator-{5554 + instance.index * 2}"

    def adb_path(self, configured_adb_path: str = "") -> Path:
        if configured_adb_path and Path(configured_adb_path).exists():
            return Path(configured_adb_path)
        if self.ldplayer_path:
            candidate = self.ldplayer_path / "adb.exe"
            if candidate.exists():
                return candidate
        candidate = self.ldconsole_path.parent / "adb.exe"
        if candidate.exists():
            return candidate
        raise LDConsoleError("adb.exe not found; set ld.adb_path or ld.ldplayer_path")

    @staticmethod
    def _target_args(instance: InstanceConfig) -> tuple[str, str]:
        if instance.launch_by == "name":
            return "--name", instance.name
        return "--index", str(instance.index)


def _ldconsole_encoding() -> str:
    if os.name == "nt":
        return "mbcs"
    return locale.getpreferredencoding(False)


def _to_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0
