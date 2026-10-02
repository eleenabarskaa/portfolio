"""Command line entry point.

    python -m maintenance_scheduler schedule --mode team
    python -m maintenance_scheduler compare
"""

from __future__ import annotations

import argparse
import logging

from .config import Config
from .pipeline import compare_modes, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maintenance_scheduler")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    schedule = sub.add_parser("schedule", help="build a plan and export it")
    schedule.add_argument("--mode", choices=["team", "technician"], default="team")
    schedule.add_argument("--no-plots", action="store_true")

    sub.add_parser("compare", help="compare the two scheduling policies")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    config = Config.load(args.config)

    if args.command == "schedule":
        result = run(config, mode=args.mode, make_plots=not args.no_plots)
        metrics = result.metrics
        print(f"\nmode                      {metrics.mode}")
        print(f"tasks scheduled           {metrics.tasks_scheduled} / {metrics.tasks_total}")
        print(f"coverage rate             {metrics.coverage_rate:.1%}")
        print(f"on-time rate              {metrics.on_time_rate:.1%}")
        print(f"on-time rate (PMK only)   {metrics.on_time_rate_metrological:.1%}")
        print(f"capacity utilisation      {metrics.utilisation_rate:.1%}")
        print(f"building switches / day   {metrics.building_switches_per_day:.2f}")
        print("\noutputs:")
        for name, path in result.outputs.items():
            print(f"  {name:<22} {path}")
        return 0

    print(compare_modes(config).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
