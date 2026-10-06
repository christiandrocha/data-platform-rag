.PHONY: help bootstrap reset-db dev down fetch-corpus index-corpus index-corpus-dry \
	index-corpus-verify reindex ask retrieval-recall fallback-eval fallback-eval-dry \
	verify-indexes eval eval-ci eval-score eval-compare eval-baseline golden-set-check golden-set-next \
	golden-set-next-architecture golden-set-next-comparison-pair \
	verify-adversarials audit-adversarials langfuse-check langfuse-flush \
	lint test precommit deploy

# `python` is not a guaranteed name: a Debian-family system without
# python-is-python3 has only `python3`, and every target below died with
# "make: python: No such file or directory". `python3` resolves correctly both
# bare and inside an activated venv, where it points at the venv interpreter.
# Override to pin a specific interpreter: make test PYTHON=.venv/bin/python
PYTHON ?= python3

# Compose ships two ways: the standalone `docker-compose` binary (v1, and v2
# installed by hand) and the `docker compose` CLI plugin. A machine with only the
# plugin has no `docker-compose` on PATH and every container target died with
# "docker-compose: command not found". Overridable for the other case:
# make bootstrap COMPOSE=docker-compose
COMPOSE ?= docker compose

# The package lives at the repo root and nothing installs it, so a script run as
# `python3 scripts/x.py` gets scripts/ on sys.path and not the root. Scripts now
# import data_platform_rag (ADR-012 moved the in-corpus set into the package),
# so they need the root. Mirrors `pythonpath = ["."]` in pyproject for pytest.
export PYTHONPATH := .:$(PYTHONPATH)

help:
	@echo "data-platform-rag — operational targets"
	@echo ""
	@echo "Environment:"
	@echo "  make bootstrap        Start Postgres+pgvector, run migrations"
	@echo "  make dev              Run Streamlit locally against local DB"
	@echo "  make down             Stop containers"
	@echo "  make reset-db         DESTRUCTIVE: drop all tables"
	@echo ""
	@echo "Data pipeline:"
	@echo "  make fetch-corpus     Clone, extract in-corpus files, write MANIFEST"
	@echo "  make index-corpus-dry Chunk the snapshot, report tokens, write nothing"
	@echo "  make index-corpus     Chunk, embed, write into pgvector"
	@echo "  make index-corpus-verify  Assert indexed corpus == verified corpus"
	@echo "  make reindex          Re-embed and rewrite everything (--force)"
	@echo ""
	@echo "Retrieval:"
	@echo "  make ask q=\"...\"      Retrieve and print ranked chunks (no LLM)"
	@echo "  make retrieval-recall Source recall at k over the golden set (ADR-014)"
	@echo "  make fallback-eval    Measure rule 3, the LLM's out-of-scope gate (ADR-020)"
	@echo "  make fallback-eval-dry  Print the assembled LLM inputs; no key, no call"
	@echo "  make index-corpus     Chunk, embed, upsert into pgvector (slice 2)"
	@echo "  make reindex          Drop and rebuild vectors (destructive)"
	@echo "  make verify-indexes   EXPLAIN ANALYZE top queries against baseline"
	@echo ""
	@echo "Evaluation:"
	@echo "  make eval             Contamination gate, generate, RAGAS score, push to Langfuse"
	@echo "  make eval-ci          The same, writing to .claude/dev/reports/"
	@echo "  make eval-score run=F Score (or resume scoring) an existing run file"
	@echo "  make eval-compare a=X b=Y  Per-metric delta, or why not comparable"
	@echo "  make eval-baseline run=R   Copy a report + its run file to docs/eval-baselines/"
	@echo "  make golden-set-check Validate golden-set YAML schema"
	@echo ""
	@echo "Observability:"
	@echo "  make langfuse-check   Verify Langfuse credentials and connectivity"
	@echo "  make langfuse-flush   Force flush pending observations"
	@echo ""
	@echo "Quality:"
	@echo "  make lint             ruff check + yamllint + bandit"
	@echo "  make test             pytest -q"
	@echo "  make precommit        Run all pre-commit hooks"
	@echo ""
	@echo "Deploy:"
	@echo "  make deploy           Push to Streamlit Cloud (via git)"

# Create-only and idempotent (ADR-013): running this against a populated
# database adds nothing and destroys nothing. The drops live in `make reset-db`.
bootstrap:
	$(COMPOSE) up -d postgres
	@sleep 3
	$(COMPOSE) exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/00_extensions.sql
	$(COMPOSE) exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/01_schema.sql
	$(COMPOSE) exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/02_indexes.sql
	$(COMPOSE) exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/03_corpus_snapshot.sql
	$(COMPOSE) exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/04_query_log_product.sql
	$(COMPOSE) exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/05_query_log_origin.sql
	@echo "✓ Postgres up, extensions installed, schema created"

# DESTRUCTIVE. The only path to a DROP. Separated from bootstrap by ADR-013:
# bootstrap is the documented ordinary way to start the database and must not be
# able to discard a populated index.
reset-db:
	$(COMPOSE) exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/90_reset.sql
	@echo "✓ tables dropped — run make bootstrap to recreate"

dev:
	streamlit run data_platform_rag/ui/app.py

down:
	$(COMPOSE) down

# ADR-012: acquisition is split from indexing. fetch-corpus creates the canonical
# snapshot that the ADR-011 adversarial gate and the Layer 2 auditor both read.
fetch-corpus:
	$(PYTHON) scripts/fetch_corpus.py

index-corpus-dry:
	$(PYTHON) scripts/index_corpus.py --dry-run $(if $(CORPUS_DIR),--corpus-dir $(CORPUS_DIR))

index-corpus:
	$(PYTHON) scripts/index_corpus.py $(if $(CORPUS_DIR),--corpus-dir $(CORPUS_DIR))

# Asserts ADR-012's purpose: the commit the rows came from == the commit the
# manifest records. Read-only.
index-corpus-verify:
	$(PYTHON) scripts/index_corpus.py --verify $(if $(CORPUS_DIR),--corpus-dir $(CORPUS_DIR))

# Indexing replaces by scope inside a transaction (ADR-013), so TRUNCATE is
# redundant and the old two-process shape — psql -c, then $(MAKE) — could leave
# the index empty if anything after the truncate failed. --force only skips the
# short-circuit that declines to re-embed an unchanged project.
reindex:
	$(PYTHON) scripts/index_corpus.py --force $(if $(CORPUS_DIR),--corpus-dir $(CORPUS_DIR))

# Retrieval, by hand. A development instrument, not a product surface: it exists
# so a golden-set question can be checked against what it actually retrieves.
#   make ask q="why Snowpipe Streaming?"
#   make ask q="..." COLLECTIONS=decisions TOP_K=5 FULL=1
ask:
	@$(PYTHON) scripts/ask.py $(if $(q),"$(q)",) \
		$(if $(COLLECTIONS),--collections $(COLLECTIONS)) \
		$(if $(TOP_K),--top-k $(TOP_K)) \
		$(if $(FULL),--full)

# ADR-014: source recall at k over the golden set. The project's retrieval metric
# until RAGAS exists. Writes .claude/dev/reports/retrieval-recall-{timestamp}.json
# baseline=FILE prints ADR-017's A1-A4 inputs against an earlier artifact.
retrieval-recall:
	$(PYTHON) scripts/retrieval_recall.py $(if $(baseline),--baseline $(baseline))

# ADR-020: does the LLM send the fallback when, and only when, it should?
# 3 runs x 80 questions = 240 Claude calls. Needs ANTHROPIC_API_KEY; without one it
# exits 2 and writes nothing. Writes .claude/dev/reports/fallback-eval-{timestamp}.json
fallback-eval:
	$(PYTHON) scripts/fallback_eval.py

# No key needed: retrieves, prints the user messages the LLM would read, calls nothing.
fallback-eval-dry:
	$(PYTHON) scripts/fallback_eval.py --dry-run

verify-indexes:
	$(COMPOSE) exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/99_verify.sql

# ADR-008. The contamination gate runs first (ADR-011): a failure stops the run
# before anything is generated. Runs land in .claude/dev/reports/ (gitignored);
# a baseline is committed through eval-baseline.
eval: verify-adversarials
	$(PYTHON) scripts/run_evaluation.py all

eval-ci: verify-adversarials
	$(PYTHON) scripts/run_evaluation.py all --out-dir .claude/dev/reports

eval-score:
	@test -n "$(run)" || (echo "usage: make eval-score run=RUN_FILE" && exit 2)
	$(PYTHON) scripts/run_evaluation.py score $(run)

eval-compare:
	@test -n "$(a)" -a -n "$(b)" || (echo "usage: make eval-compare a=REPORT b=REPORT" && exit 2)
	$(PYTHON) scripts/run_evaluation.py compare $(a) $(b)

eval-baseline:
	@test -n "$(run)" || (echo "usage: make eval-baseline run=REPORT" && exit 2)
	$(PYTHON) scripts/run_evaluation.py baseline $(run)

golden-set-check:
	$(PYTHON) scripts/validate_golden_set.py
	$(PYTHON) scripts/golden_set_coverage.py
	$(PYTHON) scripts/check_contamination.py --skip-without-snapshot $(if $(CORPUS_DIR),--corpus-dir $(CORPUS_DIR))

golden-set-next:
	@$(PYTHON) scripts/golden_set_coverage.py --next

golden-set-next-architecture:
	@$(PYTHON) scripts/golden_set_coverage.py --next-architecture

golden-set-next-comparison-pair:
	@$(PYTHON) scripts/golden_set_coverage.py --next-comparison-pair

# Layer 1 of ADR-011: literal contamination probes. Blocking precondition of eval.
# CORPUS_DIR must hold both corpus clones as subdirectories.
# CORPUS_DIR is optional: the default is the canonical /tmp/dpr-corpus-*.
verify-adversarials:
	$(PYTHON) scripts/verify_adversarials.py $(if $(CORPUS_DIR),--corpus-dir $(CORPUS_DIR))

# Layer 2 of ADR-011: Opus semantic audit of one adversarial. Advisory.
audit-adversarials:
	$(PYTHON) scripts/audit_questions.py --adversarial --question $(q) $(if $(CORPUS_DIR),--corpus-dir $(CORPUS_DIR))

langfuse-check:
	$(PYTHON) -c "from data_platform_rag.observability.langfuse_client import get_client; c = get_client(); print('Langfuse client type:', type(c).__name__)"

langfuse-flush:
	$(PYTHON) -c "from data_platform_rag.observability.langfuse_client import get_client; get_client().flush(); print('flushed')"

lint:
	ruff check data_platform_rag tests scripts
	yamllint -c .yamllint.yml docs/golden-set/ 2>/dev/null || true
	bandit -r data_platform_rag -q

test:
	pytest -q

precommit:
	pre-commit run --all-files

# Refuses unless ADR-020 is Accepted (ADR-021). The page answers visitors only
# under rule 3, and rule 3 is unmeasured until then.
deploy:
	$(PYTHON) scripts/check_deploy_gate.py
	git push origin main
	@echo "✓ Pushed. Streamlit Cloud will pick up the change."
