"""
Fortegra AI Intake Pipeline — entry point.

Usage:
    python src/run.py --scenario complaint_triage
"""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ["claims_intake", "underwriting_review", "complaint_triage"]


def main():
    parser = argparse.ArgumentParser(description="Fortegra AI Intake Pipeline")
    parser.add_argument(
        "--scenario", required=True, choices=SCENARIOS, help="The scenario to run"
    )
    args = parser.parse_args()

    scenario_path = _ROOT / "scenarios" / args.scenario / "README.md"
    if not scenario_path.exists():
        print(f"Error: Scenario README not found at {scenario_path}")
        sys.exit(1)

    if args.scenario == "complaint_triage":
        from pipeline import run_complaint_triage

        run_complaint_triage()
    else:
        print(f"Scenario '{args.scenario}' is not yet implemented.")
        sys.exit(1)


if __name__ == "__main__":
    main()
