"""
Runs the full pipeline in order so every output is regenerated from the
same code and data snapshot.

    python run_pipeline.py                 # fetch fresh data, then run everything
    python run_pipeline.py --skip-fetch    # reuse the latest raw snapshots
    python run_pipeline.py --from scoring  # resume from a step
    python run_pipeline.py --list          # show the steps

Each step runs its module as a separate process (the same as running the
file directly), and the pipeline stops at the first failure.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# (name, script, is_fetch_step, description)
STEPS: list[tuple[str, str, bool, str]] = [
    ("fetch_ev", "src/ingest/fetch_afdc.py", True, "Pull AFDC EV stations"),
    ("fetch_gas", "src/ingest/fetch_gas_stations.py", True, "Pull CEC gas stations"),
    ("fetch_census", "src/ingest/fetch_census.py", True, "Pull ACS demographics, tract shapes, population centroids"),
    ("fetch_highways", "src/ingest/fetch_highway.py", True, "Pull TIGER primary roads clipped to CA"),
    ("clean", "src/transform/clean_stations.py", False, "Clean EV (open + planned) and gas stations"),
    ("metrics", "src/analysis/coverage_metrics.py", False, "Tract coverage metrics"),
    ("deserts", "src/analysis/desert_detection.py", False, "Desert scores and severity"),
    ("scoring", "src/analysis/conversion_scoring.py", False, "Conversion candidate scores"),
    ("sensitivity", "src/analysis/phase5_delivery.py", False, "Scenario sensitivity tables"),
    ("map", "src/viz/maps.py", False, "Interactive Folium map"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-fetch", action="store_true", help="reuse the latest raw snapshots instead of downloading")
    parser.add_argument("--from", dest="start", choices=[s[0] for s in STEPS], help="start from this step")
    parser.add_argument("--list", action="store_true", help="list steps and exit")
    args = parser.parse_args(argv)

    if args.list:
        for name, script, is_fetch, desc in STEPS:
            print(f"{name:<15} {script:<38} {desc}{'  [fetch]' if is_fetch else ''}")
        return 0

    names = [s[0] for s in STEPS]
    steps = STEPS[names.index(args.start):] if args.start else STEPS
    if args.skip_fetch:
        steps = [s for s in steps if not s[2]]

    t_total = time.time()
    for name, script, _, desc in steps:
        print(f"\n=== [{name}] {desc} ({script}) ===", flush=True)
        t0 = time.time()
        result = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT)
        if result.returncode != 0:
            print(f"\nStep '{name}' failed with exit code {result.returncode}. "
                  f"Fix the error and resume with: python run_pipeline.py --from {name}"
                  + (" --skip-fetch" if args.skip_fetch else ""))
            return result.returncode
        print(f"=== [{name}] done in {time.time() - t0:.1f}s ===", flush=True)

    print(f"\nPipeline complete in {time.time() - t_total:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
