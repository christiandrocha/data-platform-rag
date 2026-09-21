# SHIPPED: Corpus acquisition and chunk measurement

## Metadata

| Field | Value |
|-------|-------|
| Feature | corpus-indexing (slice 1 of 2) |
| Shipped date | 2026-09-17 |
| PR | **none** — merged directly to `main` (`89bf480`, `06778d8`) |
| Deploy | **none exists.** `ui/app.py` is a TODO stub and no Streamlit Cloud URL has ever been published |

> Written retroactively on 2026-09-21. The feature shipped four days earlier
> without this file; the ship phase was never closed, which is why two further
> features shipped on top of it before anyone noticed.

## What users see

**Nothing.** No user-facing surface exists, and none was claimed. This slice
produces a snapshot on disk and a chunk count on a terminal.

What a *maintainer* sees is the part that matters: `make fetch-corpus` writes
`/tmp/dpr-corpus-{timestamp}/` with a `MANIFEST.json` naming the commit SHA per
project and a sha256 per file, and `make index-corpus-dry` reports **304 chunks
from 47 files**, median 209 tokens, largest 500, every one inside the 512-token
window — against `sdd-kafka-databricks@f1295df9` and
`sdd-kafka-snowflake-2@82a2e269`.

## What we learned

**Measuring before building the next slice paid for itself, once.** The dry run
fired ADR-007 rule 4 on two real files, and the resolution was to amend the ADR
rather than edit a corpus repository — the corpora are the projects this system
documents, and reformatting them to suit their consumer would invert that
relationship.

**And the measurement then exposed a defect that the failure had been hiding.**
Once the largest README stopped failing outright it produced 165 chunks, median
97 tokens, 87 of them under 100 — embeddings too small to carry meaning and
citations too fine-grained to answer with. Rule 3 always said "descending only as
far as needed"; nothing enforced it. Packing adjacent same-anchor units took that
file to 68 chunks and the corpus median from 97 to 209.

Neither would have been visible from reading the chunker. Both were found by
running it against the real corpus.

## Retrospective for the log

- **A failing check can conceal a worse defect behind it.** Rule 4's loud failure
  hid the median-97 problem completely. This repeats: `ragas.yml` hid four defects
  behind its first failing step, found on 2026-09-21.
- **Amend the ADR, never the corpus.** Established here, and it held.
- **Shipping without closing ship is how a feature folder goes stale.** This file
  is four days late, and its absence was not noticed until the next two features
  had already merged.
