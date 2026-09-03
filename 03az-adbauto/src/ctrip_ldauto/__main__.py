from __future__ import annotations

import argparse
import logging

from ctrip_ldauto.app import CtripLdAutoApp
from ctrip_ldauto.config import ConfigError, load_config
from ctrip_ldauto.ld import check_ld_instances
from ctrip_ldauto.log import setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ctrip-ldauto")
    parser.add_argument(
        "-c",
        "--config",
        help="Path to config YAML. Defaults to configs/config.yaml, then config.example.yaml.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Load and validate config, then exit.",
    )
    parser.add_argument(
        "--check-ld",
        action="store_true",
        help="Run real LDPlayer diagnostics for configured ld.instances.",
    )
    parser.add_argument(
        "--no-start-ld",
        action="store_true",
        help="With --check-ld, only inspect configured instances without launching them.",
    )
    parser.add_argument(
        "--keep-started-ld",
        action="store_true",
        help="With --check-ld, do not close emulators started by the diagnostic run.",
    )
    parser.add_argument(
        "--ld-adb-wait-seconds",
        type=int,
        help="With --check-ld, override ld.wait_device_ready_seconds for diagnostics.",
    )
    parser.add_argument(
        "--ld-running-wait-seconds",
        type=int,
        help="With --check-ld, override ld.diagnostic_running_wait_seconds.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}")
        return 1

    logger = setup_logging(config.system.data_dir, config.system.log_level)
    logger.info("ctrip-ldauto v1 starting")

    if args.check_config:
        logging.getLogger(__name__).info("Config validated: %s", config.config_path)
        return 0

    if args.check_ld:
        return _check_ld(
            config,
            start=not args.no_start_ld,
            close_started=not args.keep_started_ld,
            adb_wait_seconds=args.ld_adb_wait_seconds,
            running_wait_seconds=args.ld_running_wait_seconds,
        )

    app = CtripLdAutoApp(config)
    try:
        return app.run().code
    except KeyboardInterrupt:
        app.request_stop()
        logging.getLogger(__name__).warning("Interrupted by user")
        return 130
    except Exception:
        logging.getLogger(__name__).exception("Fatal error")
        return 1


def _check_ld(
    config,
    *,
    start: bool,
    close_started: bool,
    adb_wait_seconds: int | None,
    running_wait_seconds: int | None,
) -> int:
    results = check_ld_instances(
        config.ld,
        config.xc.app,
        start=start,
        close_started=close_started,
        running_wait_seconds=(
            running_wait_seconds
            if running_wait_seconds is not None
            else config.ld.diagnostic_running_wait_seconds
        ),
        adb_wait_seconds=(
            adb_wait_seconds
            if adb_wait_seconds is not None
            else config.ld.diagnostic_adb_wait_seconds
        ),
    )
    ok = True
    for item in results:
        item_ok = item.exists and item.running_after_launch and item.adb_ready
        ok = ok and item_ok
        print(
            " ".join(
                [
                    f"[{item.instance_id}]",
                    f"index={item.index}",
                    f"exists={item.exists}",
                    f"running_before={item.running_before}",
                    f"running_after_launch={item.running_after_launch}",
                    f"adb_ready={item.adb_ready}",
                    f"serial={item.serial or '-'}",
                    f"ctrip={item.ctrip_installed}",
                    f"pcapdroid={item.pcapdroid_installed}",
                ]
            )
        )
        if item.configured_name != item.actual_name:
            print(f"  name: configured={_safe(item.configured_name)} actual={_safe(item.actual_name)}")
        if item.error:
            print(f"  error: {item.error}")
        for suggestion in item.suggestions:
            print(f"  suggestion: {suggestion}")
    return 0 if ok else 2


def _safe(value: str) -> str:
    return value.encode("ascii", errors="backslashreplace").decode("ascii")


if __name__ == "__main__":
    raise SystemExit(main())
