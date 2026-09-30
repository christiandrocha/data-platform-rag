"""Integration tests for hybrid retrieval against real Postgres.

Vectors are chosen by hand so the RRF arithmetic can be computed on paper and
asserted exactly, rather than eyeballed. No embedding model is loaded: `search`
takes a vector, which is precisely why it was split from `retrieve`.

Geometry of the fixture, with the query vector = e0:

    A  e0                    cosine distance 0.0   text: no match
    C  0.6*e0 + 0.8*e1       cosine distance 0.4   text: no match
    B  e1                    cosine distance 1.0   text: MATCHES

so the dense ranking is A, C, B and the sparse ranking is B alone.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_platform_rag.contracts import Chunk, ChunkMetadata, IndexedSnapshot
from data_platform_rag.indexer.writer import write_project
from data_platform_rag.retrieval.hybrid_search import RRF_K, search, sparse_terms

DIM = 384
PROJECT = "sdd-kafka-snowflake-2"
QUERY_TEXT = "debezium snowflake"


def unit(*components: tuple[int, float]) -> list[float]:
    vector = [0.0] * DIM
    for index, value in components:
        vector[index] = value
    return vector


QUERY_VECTOR = unit((0, 1.0))
FIXTURE = [
    ("A", "alpha alpha alpha", unit((0, 1.0)), "decisions"),
    ("B", "debezium snowflake ingestion path", unit((1, 1.0)), "decisions"),
    ("C", "gamma gamma", unit((0, 0.6), (1, 0.8)), "decisions"),
]


def seed(conn, entries=FIXTURE, file_of=None) -> None:
    """Write the entries as one project. Each entry is its own file by default.

    `file_of` maps an entry name to a file name, to put several chunks in one
    file. ADR-017's cutoff is the chunk count of the largest file, so a fixture
    has to say which chunks share a file, not only which chunks exist.
    """
    file_of = file_of or {}
    chunks, embeddings = [], []
    for index, (name, content, vector, collection) in enumerate(entries):
        chunks.append(
            Chunk(
                content=content,
                collection=collection,
                metadata=ChunkMetadata(
                    source_project=PROJECT,
                    source_type="adr",
                    source_path=f"docs/adr/{file_of.get(name, name)}.md",
                    source_anchor=f"section {name}",
                    chunk_index=index,
                    token_count=4,
                ),
            )
        )
        embeddings.append(vector)

    snapshot = IndexedSnapshot(
        source_project=PROJECT,
        repo_url=f"https://github.com/christiandrocha/{PROJECT}",
        commit_sha="c" * 40,
        file_count=len(entries),
        manifest_created_at=datetime(2026, 9, 18, tzinfo=UTC),
        manifest_schema_version=1,
        embedding_model="fixture/hand-chosen",
        embedding_dim=DIM,
        chunk_count=len(chunks),
    )
    write_project(conn, snapshot, chunks, embeddings)


def run(conn, *, top_k=20, collections=None, text=QUERY_TEXT):
    return search(
        conn,
        query_text=text,
        query_vector=QUERY_VECTOR,
        collections=collections or ["decisions", "architecture"],
        top_k=top_k,
    )


def paths(chunks) -> list[str]:
    return [c.metadata.source_path for c in chunks]


def test_ranking_matches_rrf_computed_by_hand(conn) -> None:
    seed(conn)
    results = run(conn)

    # dense: A=1, C=2, B=3.  sparse: B=1.
    #   B = 1/(60+3) + 1/(60+1) = 0.032266   <- wins despite the worst distance
    #   A = 1/(60+1)            = 0.016393
    #   C = 1/(60+2)            = 0.016129
    assert paths(results) == ["docs/adr/B.md", "docs/adr/A.md", "docs/adr/C.md"]

    by_path = {c.metadata.source_path: c for c in results}
    assert by_path["docs/adr/B.md"].rrf_score == pytest.approx(
        1 / (RRF_K + 3) + 1 / (RRF_K + 1), abs=1e-9
    )
    assert by_path["docs/adr/A.md"].rrf_score == pytest.approx(1 / (RRF_K + 1), abs=1e-9)
    assert by_path["docs/adr/C.md"].rrf_score == pytest.approx(1 / (RRF_K + 2), abs=1e-9)


def test_a_sparse_only_chunk_gets_no_phantom_dense_contribution(conn) -> None:
    """ADR-003 Amendment 1, asserted rather than assumed.

    With top_k=2 the dense list is A and C, so B is ranked by the sparse side
    alone. Its score must be exactly the sparse contribution. The old
    COALESCE(rank, 999) form would have added 1/(60+999) = 0.000944 on top.
    """
    seed(conn)
    results = run(conn, top_k=2)

    b = next(c for c in results if c.metadata.source_path == "docs/adr/B.md")
    assert b.dense_rank is None
    assert b.sparse_rank == 1
    assert b.rrf_score == pytest.approx(1 / (RRF_K + 1), abs=1e-9)
    assert b.rrf_score != pytest.approx(1 / (RRF_K + 1) + 1 / (RRF_K + 999), abs=1e-9)


def test_dense_distance_is_real_even_for_a_sparse_only_match(conn) -> None:
    """The value exists for every candidate; only the rank is absent."""
    seed(conn)
    b = next(c for c in run(conn, top_k=2) if c.metadata.source_path == "docs/adr/B.md")
    assert b.dense_distance == pytest.approx(1.0, abs=1e-6)


def test_top_k_is_honoured_and_order_is_descending(conn) -> None:
    seed(conn)
    results = run(conn, top_k=2)
    assert len(results) <= 2
    scores = [c.rrf_score for c in results]
    assert scores == sorted(scores, reverse=True)


def test_retrieval_is_deterministic(conn) -> None:
    seed(conn)
    first = [c.id for c in run(conn)]
    second = [c.id for c in run(conn)]
    assert first == second


def test_collection_filter_excludes_the_other_collection(conn) -> None:
    seed(
        conn,
        [
            ("A", "alpha", unit((0, 1.0)), "decisions"),
            ("B", "debezium snowflake", unit((1, 1.0)), "architecture"),
        ],
    )
    decisions = run(conn, collections=["decisions"])
    assert {c.metadata.source_path for c in decisions} == {"docs/adr/A.md"}

    architecture = run(conn, collections=["architecture"])
    assert {c.metadata.source_path for c in architecture} == {"docs/adr/B.md"}


def test_a_question_matching_no_text_still_returns_dense_results(conn) -> None:
    """The sparse side contributing nothing must not empty the result."""
    seed(conn)
    results = run(conn, text="zzzz nonexistentword")
    assert len(results) == 3
    assert all(c.sparse_rank is None for c in results)
    assert all(c.dense_rank is not None for c in results)


def test_empty_index_returns_an_empty_list(conn) -> None:
    """Not an exception: an unpopulated index is a state, not a failure."""
    assert run(conn) == []


def test_every_result_is_a_fully_populated_contract(conn) -> None:
    seed(conn)
    for chunk in run(conn):
        assert chunk.metadata.source_type == "adr"
        assert chunk.metadata.token_count > 0
        assert chunk.metadata.source_anchor is not None
        assert chunk.id > 0


# ─── sanitising, empty queries and tie-breaking ──────────────────────────────
#
# Found while building ADR-015 (OR-joined lexemes), kept after its rejection:
# they guard properties that must hold whatever builds the tsquery.
#
# C matches one of the two query terms. Under plain plainto_tsquery it has no
# sparse rank; the tests below do not depend on whether it does.

SANITISING_FIXTURE = [
    ("A", "alpha alpha alpha", unit((0, 1.0)), "decisions"),
    ("B", "debezium snowflake ingestion path", unit((1, 1.0)), "decisions"),
    ("C", "gamma snowflake", unit((0, 0.6), (1, 0.8)), "decisions"),
]


@pytest.mark.parametrize("text", ["the and of is", ""])
def test_a_query_with_no_lexemes_returns_dense_only_without_error(conn, text: str) -> None:
    """An empty tsquery matches nothing; it must not raise or empty the result."""
    seed(conn, SANITISING_FIXTURE)
    results = run(conn, text=text)
    assert len(results) == 3
    assert all(c.sparse_rank is None for c in results)
    assert all(c.dense_rank is not None for c in results)


@pytest.mark.parametrize(
    "noisy",
    [
        "debezium' snowflake",
        "debezium: snowflake",
        "debezium & snowflake!",
        "debezium | snowflake",
        "debezium <-> snowflake",
        "debezium:* (snowflake)!",
        "debezium\\ snowflake",
    ],
)
def test_tsquery_syntax_in_the_input_is_inert(conn, noisy: str) -> None:
    """Sanitising still comes from plainto_tsquery: operators are just noise."""
    seed(conn, SANITISING_FIXTURE)

    def shape(chunks):
        return [(c.id, c.dense_rank, c.sparse_rank, c.rrf_score) for c in chunks]

    assert shape(run(conn, text=noisy)) == shape(run(conn, text=QUERY_TEXT))


def test_a_sparse_tie_breaks_by_id_not_by_heap_order(conn) -> None:
    """Two chunks with identical text tie on sparse_score; the lower id ranks first.

    The UPDATE rewrites the lower-id row at the end of the heap, so a sequential
    scan meets the higher id first. Without `id ASC` in the window, ROW_NUMBER
    would follow that order.

    Both chunks are in one file. In two files the ADR-017 cutoff would be 1, both
    lexemes (df 2) would be dropped, and the test would fail for a reason that has
    nothing to do with tiebreaks (ADR-017, Consequences).
    """
    seed(
        conn,
        [
            ("T1", "debezium snowflake", unit((0, 1.0)), "decisions"),
            ("T2", "debezium snowflake", unit((1, 1.0)), "decisions"),
        ],
        file_of={"T1": "T", "T2": "T"},
    )
    with conn.cursor() as cur:
        cur.execute("SELECT min(id) FROM chunks")
        low = cur.fetchone()[0]
        cur.execute("UPDATE chunks SET token_count = token_count WHERE id = %s", (low,))

    first = run(conn)
    ranks = {c.id: c.sparse_rank for c in first}
    assert ranks[low] == 1
    assert [c.id for c in run(conn)] == [c.id for c in first]


# ─── ADR-017: the document-frequency filter ──────────────────────────────────
#
# Every entry below is its own file unless `file_of` says otherwise, so the
# cutoff (chunk count of the largest file) is 1: a lexeme in two chunks is
# dropped, a lexeme in one is kept.

DF_FIXTURE = [
    ("A", "alpha alpha alpha", unit((0, 1.0)), "decisions"),
    ("B", "debezium snowflake ingestion path", unit((1, 1.0)), "decisions"),
    ("C", "gamma snowflake", unit((0, 0.6), (1, 0.8)), "decisions"),
]


def sparse_ranked(chunks) -> set[str]:
    return {c.metadata.source_path for c in chunks if c.sparse_rank is not None}


def test_a_query_whose_every_lexeme_is_above_the_cutoff_gets_no_sparse_rows(conn) -> None:
    """Not an error and not the unfiltered OR: the sparse list is just empty."""
    seed(conn, DF_FIXTURE)
    results = run(conn, text="snowflake")
    assert len(results) == 3
    assert sparse_ranked(results) == set()
    assert all(c.dense_rank is not None for c in results)


def test_kept_lexemes_are_or_joined_and_dropped_ones_do_not_vote(conn) -> None:
    """`debezium` (B) and `gamma` (C) are kept and OR-joined; `snowflake` is dropped.

    Under plainto_tsquery's AND, no chunk contains all three and the sparse side
    would be empty. Under the unfiltered OR, `snowflake` would vote for B and C.
    """
    seed(conn, DF_FIXTURE)
    results = run(conn, text="debezium gamma snowflake")
    assert sparse_ranked(results) == {"docs/adr/B.md", "docs/adr/C.md"}

    report = sparse_terms(conn, "debezium gamma snowflake")
    assert report.cutoff == 1
    assert {(t.term, t.df) for t in report.kept} == {("'debezium'", 1), ("'gamma'", 1)}
    assert {(t.term, t.df) for t in report.dropped} == {("'snowflak'", 2)}


def test_the_cutoff_follows_the_corpus_without_a_code_change(conn) -> None:
    """Put B and C in one file: the largest file has 2 chunks, `snowflake` is kept."""
    seed(conn, DF_FIXTURE)
    assert sparse_terms(conn, "snowflake").kept == []

    seed(conn, DF_FIXTURE, file_of={"B": "BC", "C": "BC"})
    report = sparse_terms(conn, "snowflake")
    assert report.cutoff == 2
    assert [(t.term, t.df, t.kept) for t in report.terms] == [("'snowflak'", 2, True)]
    assert sparse_ranked(run(conn, text="snowflake")) == {"docs/adr/BC.md"}


def test_the_filter_report_matches_the_ranking(conn) -> None:
    """A chunk is sparse-ranked only if it contains a lexeme the report kept."""
    seed(conn, DF_FIXTURE)
    report = sparse_terms(conn, QUERY_TEXT)
    assert [t.term for t in report.kept] == ["'debezium'"]
    assert [t.term for t in report.dropped] == ["'snowflak'"]
    assert sparse_ranked(run(conn)) == {"docs/adr/B.md"}


def test_quotes_and_backslashes_round_trip_through_the_cast(conn) -> None:
    """Fragments of plainto_tsquery's output are cast back; none may raise."""
    seed(conn, DF_FIXTURE)
    text = "O'Reilly back\\slash x&y a:b 'quoted'"
    assert len(run(conn, text=text)) == 3
    assert all(t.df == 0 for t in sparse_terms(conn, text).terms)


@pytest.mark.parametrize("text", ["the and of is", ""])
def test_the_filter_report_for_a_query_with_no_lexemes_is_empty(conn, text: str) -> None:
    seed(conn, DF_FIXTURE)
    report = sparse_terms(conn, text)
    assert report.cutoff == 1
    assert report.terms == []


def test_the_filter_report_on_an_empty_index_has_no_cutoff(conn) -> None:
    """No file to measure: no cutoff, and a term compared with NULL is not kept."""
    report = sparse_terms(conn, QUERY_TEXT)
    assert report.cutoff is None
    assert [(t.term, t.df, t.kept) for t in report.terms] == [
        ("'debezium'", 0, False),
        ("'snowflak'", 0, False),
    ]
