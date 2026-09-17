.PHONY: help bootstrap dev down fetch-corpus index-corpus index-corpus-dry reindex \
	verify-indexes eval eval-ci golden-set-check golden-set-next \
	golden-set-next-architecture golden-set-next-comparison-pair \
	verify-adversarials audit-adversarials langfuse-check langfuse-flush \
	lint test precommit deploy

# `python` is not a guaranteed name: a Debian-family system without
# python-is-python3 has only `python3`, and every target below died with
# "make: python: No such file or directory". `python3` resolves correctly both
# bare and inside an activated venv, where it points at the venv interpreter.
# Override to pin a specific interpreter: make test PYTHON=.venv/bin/python
PYTHON ?= python3

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
	@echo ""
	@echo "Data pipeline:"
	@echo "  make fetch-corpus     Clone, extract in-corpus files, write MANIFEST"
	@echo "  make index-corpus-dry Chunk the snapshot, report tokens, write nothing"
	@echo "  make index-corpus     Chunk, embed, upsert into pgvector (slice 2)"
	@echo "  make reindex          Drop and rebuild vectors (destructive)"
	@echo "  make verify-indexes   EXPLAIN ANALYZE top queries against baseline"
	@echo ""
	@echo "Evaluation:"
	@echo "  make eval             Run RAGAS, push scores to Langfuse (if enabled)"
	@echo "  make eval-ci          Eval + persist results with timestamp"
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

bootstrap:
	docker-compose up -d postgres
	@sleep 3
	docker-compose exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/00_extensions.sql
	docker-compose exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/01_schema.sql
	docker-compose exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/02_indexes.sql
	@echo "✓ Postgres up, extensions installed, schema created"

dev:
	streamlit run data_platform_rag/ui/app.py

down:
	docker-compose down

# ADR-012: acquisition is split from indexing. fetch-corpus creates the canonical
# snapshot that the ADR-011 adversarial gate and the Layer 2 auditor both read.
fetch-corpus:
	$(PYTHON) scripts/fetch_corpus.py

index-corpus-dry:
	$(PYTHON) scripts/index_corpus.py --dry-run $(if $(CORPUS_DIR),--corpus-dir $(CORPUS_DIR))

index-corpus:
	$(PYTHON) scripts/index_corpus.py

reindex:
	docker-compose exec -T postgres psql -U dpr -d data_platform_rag -c "TRUNCATE chunks;"
	$(MAKE) index-corpus

verify-indexes:
	docker-compose exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/99_verify.sql

eval:
	$(PYTHON) scripts/run_evaluation.py

eval-ci:
	$(PYTHON) scripts/run_evaluation.py --output .claude/dev/reports/ragas-$$(date +%Y%m%d-%H%M%S).json

golden-set-check:
	$(PYTHON) scripts/validate_golden_set.py
	$(PYTHON) scripts/golden_set_coverage.py

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

deploy:
	git push origin main
	@echo "✓ Pushed. Streamlit Cloud will pick up the change."
