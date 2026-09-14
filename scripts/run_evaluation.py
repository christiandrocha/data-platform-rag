"""Run RAGAS evaluation against the golden set.

TODO(BUILD): Implement per DESIGN.md of feature: ragas-in-ci.

Expected behavior:
1. Load docs/golden-set/evaluation_questions.yml
2. For each question, run the full pipeline (retrieval → generation)
3. Compute RAGAS metrics: faithfulness, answer relevance, context precision, context recall
4. Print summary table
5. If --output PATH, persist JSON with timestamp
6. Exit non-zero if any metric regressed > 0.05 from previous run
"""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=str, help="Persist RAGAS result to JSON")
    args = parser.parse_args()
    print("scripts/run_evaluation.py — not yet implemented (BUILD phase pending)")
    if args.output:
        print(f"Would write results to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
