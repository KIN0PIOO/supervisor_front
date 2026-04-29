"""현재 DB 매핑 룰 조회 도구.

실행:
  python tools/list_mapping_rules.py --format table
  python tools/list_mapping_rules.py --fr-table EMP --format json
"""
import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

from tools._bootstrap import ROOT_DIR  # noqa: F401
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

from agents.sql_pipeline.repositories.mapper_repository import get_all_mapping_rules


def _normalize(value: str) -> str:
    return (value or "").strip().upper()


def _matches_filter(value: str, expected: str | None) -> bool:
    if not expected:
        return True
    return _normalize(value) == _normalize(expected)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List mapping rules currently loaded by this project.")
    parser.add_argument("--fr-table", help="Filter by FR_TABLE (exact, case-insensitive).")
    parser.add_argument("--to-table", help="Filter by TO_TABLE (exact, case-insensitive).")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of rows to print. 0 means no limit.")
    parser.add_argument("--format", choices=["table", "json", "csv"], default="table", help="Output format.")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    rules = get_all_mapping_rules()
    filtered = [
        r for r in rules
        if _matches_filter(r.fr_table, args.fr_table)
        and _matches_filter(r.to_table, args.to_table)
    ]

    if args.limit > 0:
        filtered = filtered[: args.limit]

    if not filtered:
        print("No mapping rules found.")
        return

    if args.format == "json":
        print(json.dumps([asdict(r) for r in filtered], ensure_ascii=False, indent=2))
    elif args.format == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow(["map_type", "fr_table", "fr_col", "to_table", "to_col"])
        for r in filtered:
            writer.writerow([r.map_type, r.fr_table, r.fr_col, r.to_table, r.to_col])
    else:
        col_w = [10, 20, 30, 20, 30]
        header = f"{'MAP_TYPE':<{col_w[0]}}  {'FR_TABLE':<{col_w[1]}}  {'FR_COL':<{col_w[2]}}  {'TO_TABLE':<{col_w[3]}}  {'TO_COL':<{col_w[4]}}"
        print(header)
        print("-" * len(header))
        for r in filtered:
            print(f"{r.map_type:<{col_w[0]}}  {r.fr_table:<{col_w[1]}}  {r.fr_col:<{col_w[2]}}  {r.to_table:<{col_w[3]}}  {r.to_col:<{col_w[4]}}")
        print(f"\nTotal: {len(filtered)} rule(s)")


if __name__ == "__main__":
    main()
