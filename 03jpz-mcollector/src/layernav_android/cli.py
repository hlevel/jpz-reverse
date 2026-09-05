"""Command-line entry point for startup checks and runtime orchestration."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from layernav_android.config import ConfigError, load_config
from layernav_android.device import DeviceManager
from layernav_android.runtime import TaskRunner
from layernav_android.contrib.wechat_ctrip import WeChatCtripLayerModel
from layernav_android.contrib.wechat_meituan import WeChatMeituanLayerModel


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser kept separate for unit testing."""
    parser = argparse.ArgumentParser(description="Android task collector")
    parser.add_argument("--config", default="config/config.yaml", help="YAML config path")
    parser.add_argument("--check", action="store_true", help="validate config and probe devices only")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Load configuration, print startup logs, and probe configured devices."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = build_parser().parse_args(argv)
    try:
        config = load_config(Path(args.config))
    except (ConfigError, OSError) as exc:
        logging.error("configuration failed: %s", exc)
        return 2

    logging.info("configuration loaded: devices=%d tasks=%d rules=%d", len(config.devices), len(config.tasks), len(config.rules))
    sessions = list(DeviceManager(config).sessions())
    logging.info("device probe complete: online=%d/%d", len(sessions), len(config.devices))
    for device in config.devices:
        state = "enabled" if device.enabled else "disabled"
        logging.info("[%s] device (%s): %s", device.name, device.serial or "default", state)
    for device in config.devices:
        if device.enabled:
            online = any(active.name == device.name for active, _ in sessions)
            logging.info("[%s] adb: %s", device.name, "online" if online else "offline")
    if args.check:
        return 0
    sessions_by_name = {device.name: adb for device, adb in sessions}
    model_types = {
        "ctrip_mini_program": WeChatCtripLayerModel,
        "meituan_mini_program": WeChatMeituanLayerModel,
    }

    def adb_factory(device):
        return sessions_by_name[device.name]

    def model_factory(context):
        model_type = model_types.get(context.account.name)
        if model_type is None:
            raise ConfigError(f"no model registered for task {context.account.name!r}")
        logging.info("[%s] model: %s", context.device.name, model_type.__name__)
        return model_type()

    runner = TaskRunner(config, adb_factory, model_factory)
    results = runner.run_all()
    if not results:
        logging.warning("no runnable account contexts; check device/account/task/rule enabled flags")
    for key, completed in sorted(results.items()):
        logging.info("[%s] completed_tasks=%d", key.split(":", 1)[0], completed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
