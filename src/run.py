"""
Fortegra AI Intake Pipeline — Entry Point

Usage:
    python src/run.py --scenario claims_intake
    python src/run.py --scenario underwriting_review
    python src/run.py --scenario complaint_triage

This file is a stub. You are expected to implement the pipeline logic.
See the scenario README in scenarios/<scenario_name>/README.md for requirements.
"""

import argparse
import sys
from pathlib import Path

SCENARIOS = ["claims_intake", "underwriting_review", "complaint_triage"]


def main():
    parser = argparse.ArgumentParser(description="Fortegra AI Intake Pipeline")
    parser.add_argument(
        "--scenario",
        required=True,
        choices=SCENARIOS,
        help="The scenario to run"
    )
    args = parser.parse_args()

    scenario_path = Path("scenarios") / args.scenario / "README.md"
    if not scenario_path.exists():
        print(f"Error: Scenario README not found at {scenario_path}")
        sys.exit(1)

    print(f"Running scenario: {args.scenario}")
    print(f"See {scenario_path} for requirements.\n")

    # TODO: Implement your pipeline here.
    # You may structure this however makes sense for your approach.
    # The only requirements are:
    #   1. Read input data from the data/ directory
    #   2. Use the Anthropic API to process and assess the input
    #   3. Write a formatted markdown report to the output/ directory
    #
    # Feel free to add modules, helpers, or additional files under src/.
    # Document your approach clearly in your PR description.

    raise NotImplementedError(
        f"Pipeline for '{args.scenario}' is not yet implemented. "
        "This is your starting point."
    )


if __name__ == "__main__":
    main()
