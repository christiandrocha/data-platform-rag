"""Index the corpus into pgvector.

TODO(BUILD): Implement per DESIGN.md of feature: corpus-indexing.

Expected behavior:
1. Read CORPUS_REPO_* from environment
2. Clone each to /tmp/dpr-corpus-{timestamp}/{project}/
3. Walk with data_platform_rag.indexer.loader.load_corpus
4. Chunk with data_platform_rag.indexer.chunker.chunk_document
5. Embed with sentence-transformers
6. Upsert into chunks table (idempotent on source_path + chunk_index)
7. Delete /tmp/dpr-corpus-*
"""

import sys


def main() -> int:
    print("scripts/index_corpus.py — not yet implemented (BUILD phase pending)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
