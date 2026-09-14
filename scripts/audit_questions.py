"""Layer 2 of golden-set verification (ADR-011): the Opus semantic auditor.

Advisory, never authoring. This script reads questions and reports on them; it
has no code path that writes to evaluation_questions.yml. That boundary is
Commitment 1 of ADR-011 and is the reason an LLM is allowed near the golden set
at all: when a model writes a question the failure is silent and *improves* the
metrics, whereas when it audits, the failure is a wrong line in a report a human
reads.

Two modes:

* **in-scope** (default) — grounding audit. Is every claim in `expected_answer`
  supported by the cited sources? Which cited source is not actually needed?
* **adversarial** (`--adversarial`) — Layer 2 of the contamination check. Does
  the corpus discuss this topic in words the declared literal probes would miss?
  Layer 1 (`verify_adversarials.py`) catches verbatim matches deterministically
  and blocks CI; paraphrase is this mode's job.

Audits are stratified by `provenance`, per ADR-011: human-written and
LLM-proposed questions are audited separately so their contamination rates stay
comparable rather than pooled.

Corpus access reuses `verify_adversarials.py` — the same inventory-derived
allowlist, so this repository can never be read as a corpus source.

Known limitation of adversarial mode: the corpus is summarised to the ADR title
lines rather than full text, which keeps a pass cheap. A title-level scan catches
topical overlap, not a passing mention buried mid-document. A full-text variant
is possible at roughly 20x the cost and has not been needed yet.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_adversarials import corpus_projects, in_corpus_files  # noqa: E402

GOLDEN_SET = Path("docs/golden-set/evaluation_questions.yml")
INVENTORY = Path("docs/golden-set/corpus_inventory.yml")
REPORT_DIR = Path(".claude/dev/reports")

MODEL = "claude-opus-5"
# Claude Opus 5, USD per token. Used only to report what a run cost.
INPUT_PRICE = 5.0 / 1_000_000
OUTPUT_PRICE = 25.0 / 1_000_000
MAX_TOKENS = 8000

IN_SCOPE_TASK = """You are auditing one question from a RAG evaluation golden set.
You are NOT writing or rewriting questions. Report only.

Answer three things, briefly:
(a) Would someone who had NOT read the cited source phrase the question this way?
    Flag phrasing that mirrors the source's own vocabulary.
(b) Is every claim in the expected answer supported by the quoted source text?
    Flag any claim that is not. Pay particular attention to numbers, versions,
    and named mechanisms.
(c) Which cited source, if any, is not actually needed to answer the question?

Be specific and short. A human reads this and decides."""

ADVERSARIAL_TASK = """You are auditing one ADVERSARIAL question from a RAG evaluation
golden set. An adversarial question must NOT be answerable from the corpus — it
exists to verify that the system declines to answer.

A literal string search for the declared probes has already run and found no
match. Your job is the part that search cannot do.

Answer, briefly:
(a) Does the corpus discuss this topic in DIFFERENT WORDS than the declared
    probes? Paraphrase, a rebrand, a former product name, a synonym.
(b) If so, which corpus document, and what wording?
(c) Is this question still genuinely adversarial?

Note: a former product name is the classic miss. "Delta Live Tables" and
"Lakeflow Declarative Pipelines" are the same thing under two names.

Be specific and short. A human reads this and decides."""


def resolve_corpus_dir(explicit: Path | None) -> Path | None:
    """Canonical location is /tmp/dpr-corpus-*/; an explicit path overrides it.

    CI runs on a GitHub Actions runner with no ~/Documents, so /tmp is the only
    location that works in both environments and is therefore the default. A
    local override buys iteration speed at the cost of reproducibility, which is
    an acceptable trade for dev and not for CI.

    Raises on a missing or empty directory rather than returning it. An empty
    corpus directory produces a false green: every probe finds nothing, the gate
    reports success, and the contamination it exists to catch sails through. This
    is the same failure class as the IN_CORPUS_SUBPATHS = "macros" defect, where
    a path that matched nothing was skipped in silence.
    """
    if explicit is not None:
        path = explicit.expanduser()
        if not path.is_dir():
            raise SystemExit(
                f"ERROR: --corpus-dir {path} does not exist.\n"
                "  An absent corpus directory would make every probe pass vacuously.\n"
                "  Pass a real path, or run `make index-corpus` and drop the override."
            )
        if not any(path.iterdir()):
            raise SystemExit(
                f"ERROR: --corpus-dir {path} is empty.\n"
                "  An empty corpus directory produces a FALSE GREEN: every probe finds\n"
                "  nothing and the gate reports success. Refusing to run."
            )
        return path
    matches = sorted(Path("/tmp").glob("dpr-corpus-*"))
    if not matches:
        return None
    newest = matches[-1]
    if not any(newest.iterdir()):
        raise SystemExit(
            f"ERROR: canonical corpus dir {newest} is empty.\n"
            "  An empty corpus directory produces a FALSE GREEN. Re-run `make index-corpus`,\n"
            "  or pass --corpus-dir explicitly for local dev."
        )
    return newest

def load_questions(provenance: str | None, qid: str | None) -> list[dict]:
    data = yaml.safe_load(GOLDEN_SET.read_text())
    if qid:
        data = [q for q in data if q.get("id") == qid]
    if provenance:
        data = [q for q in data if q.get("provenance") == provenance]
    return data


def corpus_titles(corpus_dir: Path) -> str:
    """One title line per in-corpus markdown file. Cheap topical summary."""
    lines: list[str] = []
    for name in corpus_projects():
        repo = corpus_dir / name
        if not repo.is_dir():
            continue
        for path in sorted(in_corpus_files(repo)):
            if path.suffix != ".md":
                continue
            try:
                first = next(
                    (ln.strip() for ln in path.read_text(errors="replace").splitlines()
                     if ln.startswith("#")),
                    "",
                )
            except OSError:
                continue
            if first:
                lines.append(f"{name}/{path.relative_to(repo)}: {first.lstrip('# ')}")
    return "\n".join(lines)


def source_excerpts(q: dict, corpus_dir: Path, max_chars: int = 4000) -> str:
    out: list[str] = []
    for src in q.get("expected_source_paths") or []:
        path = corpus_dir / src["project"] / src["path"]
        if not path.is_file():
            out.append(f"--- {src['project']}/{src['path']} — NOT FOUND ---")
            continue
        out.append(f"--- {src['project']}/{src['path']} ---\n"
                   + path.read_text(errors="replace")[:max_chars])
    return "\n\n".join(out)


def build_prompt(q: dict, corpus_dir: Path, adversarial: bool) -> str:
    if adversarial:
        return (
            f"{ADVERSARIAL_TASK}\n\n"
            f"QUESTION: {q['question']}\n"
            f"DECLARED PROBES: {q.get('contamination_probes')}\n\n"
            f"CORPUS DOCUMENT TITLES:\n{corpus_titles(corpus_dir)}"
        )
    return (
        f"{IN_SCOPE_TASK}\n\n"
        f"QUESTION: {q['question']}\n"
        f"EXPECTED ANSWER: {q['expected_answer']}\n\n"
        f"CITED SOURCES:\n{source_excerpts(q, corpus_dir)}"
    )


def audit(client, prompt: str) -> tuple[str, int, int]:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    text = "\n".join(b.text for b in resp.content if b.type == "text")
    return text, resp.usage.input_tokens, resp.usage.output_tokens


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-dir", type=Path, default=None,
        help="Corpus clones root. Defaults to the newest /tmp/dpr-corpus-* (canonical); "
             "pass a path to override for local dev.",
    )
    parser.add_argument("--question", help="Audit a single question by id")
    parser.add_argument("--provenance", choices=["human", "llm"],
                        help="Audit only this provenance stratum (ADR-011)")
    parser.add_argument("--adversarial", action="store_true",
                        help="Layer 2 semantic contamination check")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print prompts and the estimated cost; call nothing")
    args = parser.parse_args()

    corpus_dir = resolve_corpus_dir(args.corpus_dir)
    if corpus_dir is None:
        print("ERROR: no /tmp/dpr-corpus-* found. Run `make index-corpus`, or pass "
              "--corpus-dir for local dev.")
        return 1

    questions = load_questions(args.provenance, args.question)
    if args.adversarial:
        questions = [q for q in questions if q.get("intent") == "out-of-scope"]
    else:
        questions = [q for q in questions if q.get("intent") != "out-of-scope"]
    if not questions:
        print("No questions matched the given filters.")
        return 1

    prompts = [(q, build_prompt(q, corpus_dir, args.adversarial)) for q in questions]

    if args.dry_run:
        est_in = sum(len(p) // 4 for _, p in prompts)
        est_out = 150 * len(prompts)
        cost = est_in * INPUT_PRICE + est_out * OUTPUT_PRICE
        print(f"{len(prompts)} question(s), mode="
              f"{'adversarial' if args.adversarial else 'in-scope'}")
        print(f"estimated ~{est_in} input + ~{est_out} output tokens ≈ ${cost:.4f}")
        for q, p in prompts:
            print(f"\n{'=' * 70}\n{q['id']} ({q.get('provenance')})\n{'=' * 70}\n{p[:600]}...")
        return 0

    import anthropic

    from data_platform_rag.config import get_settings

    client = anthropic.Anthropic(
        api_key=get_settings().anthropic_api_key.get_secret_value()
    )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    kind = "adversarial" if args.adversarial else "golden-set"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = REPORT_DIR / f"audit-{kind}-{len(questions)}q-{stamp}.md"

    total_in = total_out = 0
    lines = [
        f"# Layer 2 audit — {kind}",
        "",
        f"- Model: `{MODEL}`",
        f"- Run: {stamp}",
        f"- Questions: {len(questions)}",
        f"- Provenance filter: {args.provenance or 'all'}",
        "",
        "Advisory only. A human decides. Disagreement with any finding below must",
        "be recorded on this entry with reasoning, per ADR-011 Commitment 1.",
        "",
    ]
    for q, prompt in prompts:
        text, n_in, n_out = audit(client, prompt)
        total_in += n_in
        total_out += n_out
        lines += [f"## {q['id']} ({q.get('provenance')}, {q.get('intent')})", "",
                  q["question"], "", text, "",
                  f"*{n_in} in / {n_out} out tokens*", ""]
        print(f"  {q['id']}: {n_in} in / {n_out} out")

    cost = total_in * INPUT_PRICE + total_out * OUTPUT_PRICE
    lines += ["---", "",
              f"**Usage**: {total_in} input + {total_out} output tokens ≈ ${cost:.4f}"]
    report.write_text("\n".join(lines))
    print(f"\n✓ {report}  ({total_in} in / {total_out} out ≈ ${cost:.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
