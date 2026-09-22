"""Exit rule of the golden-set coverage report (DESIGN property 3)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from golden_set_coverage import report_exit  # noqa: E402


def test_uncovered_adrs_only_warn_below_fifty():
    assert report_exit(n_uncovered=18, n_questions=5) == 0


def test_uncovered_adr_fails_the_finished_set():
    assert report_exit(n_uncovered=1, n_questions=50) == 1


def test_full_coverage_at_fifty_passes():
    assert report_exit(n_uncovered=0, n_questions=50) == 0
