"""CLI: profile a file and emit Excel report."""

from __future__ import annotations

import argparse
from pathlib import Path

from dq_tool.excel_export import profile_to_excel
from dq_tool.profiler import profile_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Data quality profile → Excel")
    parser.add_argument("input", type=str, help="Path to CSV, Parquet, Excel, JSON, etc.")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="",
        help="Output .xlsx path (default: <input_basename>_dq_report.xlsx)",
    )
    parser.add_argument("--sample-rows", type=int, default=10, help="Rows in Sample_Data sheet")
    args = parser.parse_args()

    inp = Path(args.input)
    out = Path(args.output) if args.output else inp.with_name(f"{inp.stem}_dq_report.xlsx")

    df, prof = profile_file(inp)
    profile_to_excel(prof, df, out, sample_rows=args.sample_rows)
    print(f"Report written: {out.resolve()}")


if __name__ == "__main__":
    main()
