"""Real token counting for the ADR-007 budget assertions.

ADR-007's rules are denominated in tokens against a 512-token embedding window.
A word count is not a token count, and a proxy that looks like a measurement and
is not one would be worse than no measurement at all — so when no tokenizer is
available this module raises rather than approximating.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

_INSTALL_HINT = (
    "  Install one of:\n"
    "    pip install tokenizers        # light, pulls the vocab from the Hub\n"
    "    pip install sentence-transformers  # the full runtime, per pyproject\n"
    "  A first run needs network access to fetch the vocabulary; it is cached after."
)


@lru_cache(maxsize=4)
def get_token_counter(model_name: str) -> Callable[[str], int]:
    """Return a token counter for `model_name`, or raise with what to install.

    Cached per model: loading a vocabulary is slow and the dry run counts every
    unit in the corpus several times while descending the split hierarchy.
    """
    try:
        from tokenizers import Tokenizer
    except ImportError as exc:  # pragma: no cover — environment-dependent
        raise SystemExit(
            f"ERROR: no tokenizer available, so ADR-007's token budget cannot be "
            f"checked.\n{_INSTALL_HINT}"
        ) from exc

    try:
        tokenizer = Tokenizer.from_pretrained(model_name)
    except Exception as exc:  # pragma: no cover — network/cache-dependent
        raise SystemExit(
            f"ERROR: could not load the tokenizer for {model_name!r}: {exc}\n"
            f"  The dry run refuses to substitute a word count for a token count.\n"
            f"{_INSTALL_HINT}"
        ) from exc

    def count(text: str) -> int:
        return len(tokenizer.encode(text).ids)

    return count
