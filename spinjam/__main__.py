from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from spinjam.config import load_config
from spinjam.service import SpinJamService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SpinJam vinyl capture / recognition node")
    parser.add_argument(
        "-c",
        "--config",
        default="config.yaml",
        help="Path to config YAML (default: config.yaml)",
    )
    parser.add_argument(
        "--file",
        dest="file_path",
        default=None,
        help="Override capture to file mode with this WAV path",
    )
    parser.add_argument(
        "--no-shazam",
        action="store_true",
        help="Disable Shazam; use fixture identifier when audio is loud enough",
    )
    parser.add_argument(
        "--no-realtime",
        action="store_true",
        help="In file mode, process as fast as possible (for soak/CI)",
    )
    parser.add_argument(
        "--mqtt-host",
        default=None,
        help="Override MQTT broker host",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config)
    if not config_path.exists():
        example = Path("config.example.yaml")
        if example.exists() and args.config == "config.yaml":
            print(
                f"No {config_path}; copy config.example.yaml to config.yaml and edit.",
                file=sys.stderr,
            )
            return 2
        print(f"Config not found: {config_path}", file=sys.stderr)
        return 2

    config = load_config(config_path)
    if args.file_path:
        config.capture.mode = "file"
        config.capture.file_path = args.file_path
    if args.no_realtime:
        config.capture.file_realtime = False
    if args.no_shazam:
        config.identify.use_shazam = False
    if args.mqtt_host:
        config.mqtt.host = args.mqtt_host

    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    service = SpinJamService(config)
    service.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
