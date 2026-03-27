from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from .batch_export import export_batch, export_single
from .config import load_config


LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plot GNSS ionospheric netCDF maps.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("single", "batch"):
        subparser = subparsers.add_parser(command, help=f"Run {command} export mode.")
        subparser.add_argument(
            "--config",
            required=True,
            help="Path to the TOML config file.",
        )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(Path(args.config), args.command)
        if config.data.mode and config.data.mode != args.command:
            LOGGER.info(
                "CLI mode '%s' overrides config data.mode '%s'.",
                args.command,
                config.data.mode,
            )

        if args.command == "single":
            export_single(config)
        else:
            export_batch(config)
        return 0
    except Exception as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
