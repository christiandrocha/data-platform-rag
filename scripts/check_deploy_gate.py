"""Refuse a deploy until rule 3 is measured and Accepted (ADR-021).

The page answers visitors under rule 3 of the system prompt, the only
out-of-scope gate since ADR-019. ADR-020 measures it. Until ADR-020's Status
starts with `Accepted`, `make deploy` stops here.

This is one of two gates. `make deploy` is a `git push`, so a Streamlit Cloud app
tracking `main` would publish on any merge whatever this script says. The other
gate is the key: no `ANTHROPIC_API_KEY` in Streamlit Cloud's secrets before
ADR-020 is Accepted, and without it the page runs nothing.

Exit 0 when the gate is open, 1 when it is closed. It reads one line of one
file and touches nothing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ADR_020 = Path("docs/adr/ADR-020-llm-rule-3-as-the-out-of-scope-gate.md")

_STATUS = re.compile(r"^\*\*Status\*\*:\s*(.+)$", re.MULTILINE)


def gate_status(adr_path: Path) -> tuple[bool, str]:
    """(open, reason). Open only when the Status line starts with `Accepted`."""
    if not adr_path.is_file():
        return False, f"{adr_path} not found"
    match = _STATUS.search(adr_path.read_text(encoding="utf-8"))
    if match is None:
        return False, f"{adr_path} has no **Status** line"
    status = match.group(1).strip()
    if status.startswith("Accepted"):
        return True, f"ADR-020 status: {status}"
    return False, f"ADR-020 status: {status}"


def main() -> int:
    is_open, reason = gate_status(ADR_020)
    if is_open:
        print(f"✓ deploy gate open. {reason}")
        return 0
    print(
        f"✗ deploy refused. {reason}\n"
        "  The page answers under rule 3, which ADR-020 has not Accepted (ADR-021).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
