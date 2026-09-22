"""Pure functions and the skip rule of the contamination check."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import check_contamination  # noqa: E402
from check_contamination import quote_in_source, shared_spans, words  # noqa: E402

SOURCE = "The registry is also the metadata source of truth for every domain."


def test_words_lowercase_and_drop_punctuation():
    assert words("The v4 Connector, ADR-0030.") == ["the", "v4", "connector", "adr", "0030"]


def test_eight_shared_words_are_a_hit():
    q = "Why is the metadata source of truth for every domain the registry?"
    assert shared_spans(q, SOURCE) == ["the metadata source of truth for every domain"]


def test_seven_shared_words_are_not_a_hit():
    q = "Why is the metadata source of truth for every table the registry?"
    assert shared_spans(q, SOURCE) == []


def test_case_whitespace_and_punctuation_do_not_hide_a_hit():
    q = "THE  METADATA source,\nof truth for\tevery domain?"
    assert shared_spans(q, SOURCE) == ["the metadata source of truth for every domain"]


def test_quote_matches_across_a_line_wrap():
    assert quote_in_source("metadata source of truth", "the metadata\n  source of truth")


def test_paraphrased_quote_is_not_found():
    assert not quote_in_source("metadata single source of truth", SOURCE)


def test_skip_flag_exits_zero_without_snapshot(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(check_contamination, "SNAPSHOT_PARENT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_contamination.py", "--skip-without-snapshot"])
    assert check_contamination.main() == 0
    assert "SKIPPED" in capsys.readouterr().out


def test_without_skip_flag_a_missing_snapshot_fails(tmp_path, monkeypatch):
    import data_platform_rag.indexer.corpus as corpus

    monkeypatch.setattr(corpus, "SNAPSHOT_PARENT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_contamination.py"])
    with pytest.raises(SystemExit):
        check_contamination.main()
