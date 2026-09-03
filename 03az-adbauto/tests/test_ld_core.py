from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from ctrip_ldauto.config import InstanceConfig, LdConfig
from ctrip_ldauto.ld import AdbDevice, EmulatorManager, LDConsoleClient, StartedEmulator
from ctrip_ldauto.ld.adb import AdbError
from ctrip_ldauto.ld.device import EmulatorDevice
from ctrip_ldauto.ld.ldconsole import LDConsoleError


class LDConsoleClientTests(unittest.TestCase):
    def test_resolves_configured_ldconsole_and_adb_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ldconsole = root / "ldconsole.exe"
            adb = root / "adb.exe"
            ldconsole.write_text("", encoding="utf-8")
            adb.write_text("", encoding="utf-8")

            client = LDConsoleClient(
                LdConfig(ldconsole_path=str(ldconsole), instances=[InstanceConfig("ld01", "LD", 0)])
            )

            self.assertEqual(client.ldconsole_path, ldconsole)
            self.assertEqual(client.adb_path(), adb)

    def test_resolves_ldconsole_from_multiplayer_pathconfig(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            multiplayer = root / "ldmutiplayer"
            player14 = root / "LDPlayer14"
            multiplayer.mkdir()
            player14.mkdir()
            (multiplayer / "dnmultiplayerex.exe").write_text("", encoding="utf-8")
            (multiplayer / "pathconfig.ini").write_text(
                "[setting]\nplayer14={0}\\\n".format(player14),
                encoding="utf-8",
            )
            ldconsole = player14 / "ldconsole.exe"
            adb = player14 / "adb.exe"
            ldconsole.write_text("", encoding="utf-8")
            adb.write_text("", encoding="utf-8")

            client = LDConsoleClient(
                LdConfig(
                    multiplayer_path=str(multiplayer / "dnmultiplayerex.exe"),
                    instances=[InstanceConfig("ld01", "LD", 0)],
                )
            )

            self.assertEqual(client.ldconsole_path, ldconsole)
            self.assertEqual(client.adb_path(), adb)

    def test_list_instances_supports_simple_and_csv_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ldconsole = Path(tmp) / "ldconsole.exe"
            ldconsole.write_text("", encoding="utf-8")
            client = LDConsoleClient(
                LdConfig(ldconsole_path=str(ldconsole), instances=[InstanceConfig("ld01", "LD", 0)])
            )

            with patch.object(client, "run", return_value="LDPlayer-1\nLDPlayer-2"):
                self.assertEqual(
                    client.list_instances(),
                    [{"index": 0, "name": "LDPlayer-1"}, {"index": 1, "name": "LDPlayer-2"}],
                )

            with patch.object(client, "run", return_value="0,LDPlayer-1,top\n1,LDPlayer-2,top"):
                self.assertEqual(
                    client.list_instances(),
                    [{"index": 0, "name": "LDPlayer-1"}, {"index": 1, "name": "LDPlayer-2"}],
                )

    def test_serial_falls_back_to_ldplayer_port_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ldconsole = Path(tmp) / "ldconsole.exe"
            ldconsole.write_text("", encoding="utf-8")
            client = LDConsoleClient(
                LdConfig(ldconsole_path=str(ldconsole), instances=[InstanceConfig("ld02", "LD", 1)])
            )

            with patch.object(client, "run", side_effect=LDConsoleError("adb failed")):
                self.assertEqual(client.serial(1), "emulator-5556")


class AdbDeviceTests(unittest.TestCase):
    def test_run_retries_then_returns_stdout(self) -> None:
        device = AdbDevice(Path("adb.exe"), "emulator-5554")
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_: object) -> SimpleNamespace:
            calls.append(cmd)
            if len(calls) == 1:
                return SimpleNamespace(returncode=1, stdout="", stderr="offline")
            return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

        with patch("ctrip_ldauto.ld.adb.subprocess.run", side_effect=fake_run), patch(
            "ctrip_ldauto.ld.adb.time.sleep", return_value=None
        ):
            self.assertEqual(device.run("shell", "echo", "ok"), "ok")

        self.assertEqual(len(calls), 2)

    def test_package_installed_maps_adb_error_to_false(self) -> None:
        device = AdbDevice(Path("adb.exe"), "emulator-5554")
        with patch.object(device, "run", side_effect=AdbError("missing")):
            self.assertFalse(device.is_package_installed("missing.package"))

    def test_screenshot_uses_exec_out(self) -> None:
        device = AdbDevice(Path("adb.exe"), "emulator-5554")
        with patch(
            "ctrip_ldauto.ld.adb.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=b"png", stderr=b""),
        ) as run:
            self.assertEqual(device.screenshot(), b"png")

        self.assertEqual(run.call_args.args[0], ["adb.exe", "-s", "emulator-5554", "exec-out", "screencap", "-p"])


class EmulatorManagerTests(unittest.TestCase):
    def test_start_configured_skips_failed_instances(self) -> None:
        instances = [
            InstanceConfig("ld01", "LD 1", 0),
            InstanceConfig("ld02", "LD 2", 1),
        ]
        manager = EmulatorManager.__new__(EmulatorManager)
        manager.config = LdConfig(instances=instances, wait_device_ready_seconds=1)
        manager.adb_path = Path("adb.exe")
        manager.ldconsole = Mock()
        manager.ldconsole.is_running_instance.side_effect = [True, False]
        manager.ldconsole.serial_instance.side_effect = ["emulator-5554", "emulator-5556"]
        manager.ldconsole.launch_instance.side_effect = RuntimeError("launch failed")

        with patch("ctrip_ldauto.ld.manager.AdbDevice") as adb_cls, patch(
            "ctrip_ldauto.ld.manager.LOG"
        ):
            adb_cls.return_value.wait_ready.return_value = True
            started = manager.start_configured()

        self.assertEqual([item.device.id for item in started], ["ld01"])
        self.assertTrue(started[0].already_running)

    def test_quit_only_closes_instances_started_by_us(self) -> None:
        manager = EmulatorManager.__new__(EmulatorManager)
        manager.ldconsole = Mock()
        adb = Mock()
        started = [
            StartedEmulator(EmulatorDevice(InstanceConfig("ld01", "LD 1", 0), adb), already_running=True),
            StartedEmulator(EmulatorDevice(InstanceConfig("ld02", "LD 2", 1), adb), already_running=False),
        ]

        manager.quit_started_by_us(started)

        manager.ldconsole.quit_instance.assert_called_once_with(started[1].device.instance)


if __name__ == "__main__":
    unittest.main()
