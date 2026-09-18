"""The pgvector writer — the only module in the package that writes to Postgres.

Implements ADR-013. Two decisions shape everything here:

**Replace by scope, not upsert.** For each project, in one transaction: delete
that project's `corpus_snapshot` row — the `ON DELETE CASCADE` takes its chunks
with it — then insert the new snapshot row and all of that project's chunks.
`ON CONFLICT DO UPDATE` was the alternative and is blind to rows that should no
longer exist: a source file deleted upstream, or a section that now packs into
four chunks where it once produced six, leaves orphans the upsert never visits.
Those orphans are retrievable, and they are the worst possible retrievable
content — text no longer in the corpus, citable against a path that no longer
contains it.

**The guard runs before the transaction.** A wrong-length vector is a refusal,
not a rollback. Everything that can fail outside the database does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from data_platform_rag.contracts import Chunk, IndexedSnapshot, SourceProject

if TYPE_CHECKING:  # pragma: no cover - typing only
    import psycopg


class DimensionMismatch(ValueError):
    """An embedding whose length is not the column's width.

    Raised before any SQL runs. Postgres would reject the vector too, but it
    would report it from inside a batch insert, naming a parameter index rather
    than the chunk — and by then the transaction is already open.
    """


class EmbeddingCountMismatch(ValueError):
    """`chunks` and `embeddings` are not the same length.

    They are parallel lists, and `zip` would silently truncate to the shorter of
    the two — writing a corpus that is quietly missing its tail.
    """


# The column list is written once. `content_tsv` is GENERATED ALWAYS and `id`
# and `created_at` have defaults, so none of the three appears here.
_CHUNK_COLUMNS = (
    "collection",
    "content",
    "embedding",
    "source_project",
    "source_type",
    "source_path",
    "source_anchor",
    "adr_id",
    "topic",
    "status",
    "keywords",
    "chunk_index",
    "token_count",
    "snapshot_id",
)

# The f-string interpolates `_CHUNK_COLUMNS` above and nothing else: a literal
# tuple defined in this module, never a caller's input. Every value is bound
# through a %s placeholder by psycopg. Built rather than written out so the
# column list and the placeholder count cannot drift apart.
_COLUMN_LIST = ", ".join(_CHUNK_COLUMNS)
_PLACEHOLDERS = ", ".join(["%s"] * len(_CHUNK_COLUMNS))
_INSERT_CHUNK = f"INSERT INTO chunks ({_COLUMN_LIST}) VALUES ({_PLACEHOLDERS})"  # nosec B608

_INSERT_SNAPSHOT = """
    INSERT INTO corpus_snapshot (
        source_project, repo_url, commit_sha, file_count,
        manifest_created_at, manifest_schema_version,
        embedding_model, embedding_dim, chunk_count
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
"""

_SELECT_SNAPSHOTS = """
    SELECT source_project, repo_url, commit_sha, file_count,
           manifest_created_at, manifest_schema_version,
           embedding_model, embedding_dim, chunk_count
    FROM corpus_snapshot
    ORDER BY source_project
"""


def guard_dimensions(
    chunks: list[Chunk],
    embeddings: list[list[float]],
    expected_dim: int,
) -> None:
    """Refuse a batch whose vectors do not match the column width.

    Pure and database-free on purpose: it is the one check that must run before
    a connection is opened, and it is the one check worth testing without one.
    """
    if len(chunks) != len(embeddings):
        raise EmbeddingCountMismatch(
            f"{len(chunks)} chunk(s) but {len(embeddings)} embedding(s). "
            f"These are parallel lists; zipping them would silently drop the tail."
        )
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        if len(embedding) != expected_dim:
            meta = chunk.metadata
            raise DimensionMismatch(
                f"{meta.source_project}/{meta.source_path} "
                f"[chunk_index={meta.chunk_index}]: embedding has {len(embedding)} "
                f"dimensions, column expects {expected_dim}."
            )


def connect(dsn: str) -> psycopg.Connection:
    """Open a connection with the pgvector adapter registered.

    Registration is per-connection, not global, which is why this helper exists
    rather than callers calling `psycopg.connect` directly: a connection without
    it sends vectors as strings and the failure is a type error deep in an
    insert.
    """
    import psycopg
    from pgvector.psycopg import register_vector

    conn = psycopg.connect(dsn)
    register_vector(conn)
    return conn


def current_snapshots(conn: psycopg.Connection) -> dict[SourceProject, IndexedSnapshot]:
    """What is indexed right now, keyed by project.

    Feeds both the re-index short-circuit and `--verify`. An empty dict means
    nothing is indexed, which is a normal state and not an error.
    """
    with conn.cursor() as cur:
        cur.execute(_SELECT_SNAPSHOTS)
        rows = cur.fetchall()

    snapshots: dict[SourceProject, IndexedSnapshot] = {}
    for row in rows:
        snapshot = IndexedSnapshot(
            source_project=row[0],
            repo_url=row[1],
            commit_sha=row[2],
            file_count=row[3],
            manifest_created_at=row[4],
            manifest_schema_version=row[5],
            embedding_model=row[6],
            embedding_dim=row[7],
            chunk_count=row[8],
        )
        snapshots[snapshot.source_project] = snapshot
    return snapshots


def write_project(
    conn: psycopg.Connection,
    snapshot: IndexedSnapshot,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> int:
    """Replace one project's scope. Returns the number of chunk rows written.

    The whole body is one transaction. The caller owns the connection's lifetime
    so that a test can hand in a connection inside a rolled-back outer
    transaction, and so that a multi-project run can decide for itself whether
    one project's failure should abandon the others.

    The delete is what makes this idempotent, and it is also what makes a
    mixed-commit index unrepresentable: `uq_corpus_snapshot_project` allows one
    live row per project, so the new row cannot be inserted until the old one
    and its chunks are gone.
    """
    guard_dimensions(chunks, embeddings, snapshot.embedding_dim)

    if snapshot.chunk_count != len(chunks):
        raise ValueError(
            f"{snapshot.source_project}: snapshot declares chunk_count="
            f"{snapshot.chunk_count} but {len(chunks)} chunk(s) were supplied. "
            f"The provenance row must describe the rows it is written with."
        )

    from pgvector import Vector

    with conn.transaction():
        with conn.cursor() as cur:
            # The cascade removes this project's chunks. Nothing else is touched:
            # the other project's snapshot row, and therefore its chunks, survive.
            cur.execute(
                "DELETE FROM corpus_snapshot WHERE source_project = %s",
                (snapshot.source_project,),
            )
            cur.execute(
                _INSERT_SNAPSHOT,
                (
                    snapshot.source_project,
                    str(snapshot.repo_url),
                    snapshot.commit_sha,
                    snapshot.file_count,
                    snapshot.manifest_created_at,
                    snapshot.manifest_schema_version,
                    snapshot.embedding_model,
                    snapshot.embedding_dim,
                    snapshot.chunk_count,
                ),
            )
            row = cur.fetchone()
            if row is None:  # pragma: no cover - RETURNING always yields a row
                raise RuntimeError("corpus_snapshot INSERT returned no id")
            snapshot_id = row[0]

            cur.executemany(
                _INSERT_CHUNK,
                [
                    (
                        chunk.collection,
                        chunk.content,
                        Vector(embedding),
                        chunk.metadata.source_project,
                        chunk.metadata.source_type,
                        chunk.metadata.source_path,
                        chunk.metadata.source_anchor,
                        chunk.metadata.adr_id,
                        chunk.metadata.topic,
                        chunk.metadata.status,
                        chunk.metadata.keywords,
                        chunk.metadata.chunk_index,
                        chunk.metadata.token_count,
                        snapshot_id,
                    )
                    for chunk, embedding in zip(chunks, embeddings, strict=True)
                ],
            )

    return len(chunks)
