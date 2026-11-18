"""Command line: gisqa data.gpkg --rules rules.json --out reports/"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import ConfigError, QAConfig, load_config

EXIT_OK, EXIT_ISSUES, EXIT_USAGE = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gisqa",
        description="Rule-based data quality checks for GIS data (no ArcGIS license needed).",
    )
    parser.add_argument("dataset", help="GeoPackage, shapefile, GeoJSON or file geodatabase")
    parser.add_argument("--layer", help="Layer name inside a GeoPackage or geodatabase")
    parser.add_argument("--rules", help="Rules file (JSON)")
    parser.add_argument("--key-field", help="Field that must be unique")
    parser.add_argument("--required", help="Comma-separated required fields")
    parser.add_argument("--min-area", type=float, help="Flag polygons smaller than this many square meters")
    parser.add_argument("--oid-field", help="Field to report as the feature ID (default: row number)")
    parser.add_argument("--out", default="qa_reports", help="Report folder (default: qa_reports)")
    parser.add_argument(
        "--fail-on",
        choices=["error", "warning", "never"],
        default="error",
        help="Exit with code 1 when issues of this severity exist (default: error)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    # Imported here so `gisqa --help` works without the geo stack
    from .engine import run_checks
    from .geopandas_adapter import read_records
    from .report import write_reports

    try:
        config = load_config(args.rules) if args.rules else QAConfig()
        config = config.with_overrides(
            key_field=args.key_field,
            required_fields=[f.strip() for f in args.required.split(",")] if args.required else None,
            min_area_m2=args.min_area,
        )
        records, fields, count = read_records(args.dataset, layer=args.layer, oid_field=args.oid_field)
        print(f"Checking {count} features in {args.dataset}{f' ({args.layer})' if args.layer else ''}...")
        result = run_checks(records, config, available_fields=fields)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as error:  # noqa: BLE001 - unreadable dataset, missing layer, etc.
        print(f"Could not read {args.dataset}: {error}", file=sys.stderr)
        return EXIT_USAGE

    basename = Path(args.dataset).stem + (f"_{args.layer}" if args.layer else "") + "_qa"
    paths = write_reports(result, args.out, basename)

    print(
        f"{result.records_checked} checked, {result.records_with_issues} with issues, "
        f"{result.error_count} errors, {result.warning_count} warnings (pass rate {result.pass_rate:.1%})"
    )
    for rule, n in result.counts_by_rule().items():
        print(f"  {rule:<20} {n}")
    print(f"Report: {paths['html']}")

    if args.fail_on == "error" and result.error_count:
        return EXIT_ISSUES
    if args.fail_on == "warning" and (result.error_count or result.warning_count):
        return EXIT_ISSUES
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
