"""Run the end-of-day position, cash and best-execution checks.

Usage:
    python -m recon.main                 # generate a fresh trading day, then run
    python -m recon.main --use-existing  # run on the CSVs already in data/
"""
import argparse
import os

import pandas as pd

from recon import best_execution, positions
from recon.generate import DATA_DIR, ROOT, expected_eod, generate

OUTPUT_DIR = os.path.join(ROOT, "output")


def load(data_dir=DATA_DIR):
    read = lambda name: pd.read_csv(os.path.join(data_dir, name))  # noqa: E731
    return {
        "sod_positions": read("sod_positions.csv"),
        "sod_cash": read("sod_cash.csv"),
        "trades": read("trades.csv"),
        "custodian_positions": read("custodian_positions.csv"),
        "custodian_cash": read("custodian_cash.csv"),
    }


def run(use_existing=False, data_dir=DATA_DIR, output_dir=OUTPUT_DIR, quiet=False):
    if not use_existing:
        generate(out_dir=data_dir)
    d = load(data_dir)
    exp_pos, exp_cash = expected_eod(d["sod_positions"], d["sod_cash"], d["trades"])

    results = {
        "position_breaks": positions.reconcile_positions(exp_pos, d["custodian_positions"], d["trades"]),
        "cash_breaks": positions.reconcile_cash(exp_cash, d["custodian_cash"]),
        "venue_scorecard": best_execution.venue_scorecard(d["trades"]),
        "trade_throughs": best_execution.trade_throughs(d["trades"]),
    }

    os.makedirs(output_dir, exist_ok=True)
    for name, df in results.items():
        df.to_csv(os.path.join(output_dir, f"{name}.csv"), index=False)

    if not quiet:
        pd.set_option("display.width", 160)
        print(f"Position breaks: {len(results['position_breaks'])}")
        print(results["position_breaks"].to_string(index=False), "\n")
        print(f"Cash breaks: {len(results['cash_breaks'])}")
        print(results["cash_breaks"].to_string(index=False), "\n")
        print("Best execution by venue:")
        print(results["venue_scorecard"].to_string(index=False), "\n")
        print(f"Trade-throughs needing review: {len(results['trade_throughs'])}")
        print(f"\nCSV outputs written to {output_dir}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--use-existing", action="store_true")
    run(parser.parse_args().use_existing)
