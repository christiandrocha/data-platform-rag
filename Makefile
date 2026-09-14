.PHONY: help bootstrap dev down index-corpus reindex verify-indexes eval eval-ci golden-set-check langfuse-check langfuse-flush lint test precommit deploy

help:
	@echo "data-platform-rag — operational targets"
	@echo ""
	@echo "Environment:"
	@echo "  make bootstrap        Start Postgres+pgvector, run migrations"
	@echo "  make dev              Run Streamlit locally against local DB"
	@echo "  make down             Stop containers"
	@echo ""
	@echo "Data pipeline:"
	@echo "  make index-corpus     Clone repos, chunk, embed, upsert into pgvector"
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

index-corpus:
	python scripts/index_corpus.py

reindex:
	docker-compose exec -T postgres psql -U dpr -d data_platform_rag -c "TRUNCATE chunks;"
	$(MAKE) index-corpus

verify-indexes:
	docker-compose exec -T postgres psql -U dpr -d data_platform_rag -f - < sql/99_verify.sql

eval:
	python scripts/run_evaluation.py

eval-ci:
	python scripts/run_evaluation.py --output .claude/dev/reports/ragas-$$(date +%Y%m%d-%H%M%S).json

golden-set-check:
	python scripts/validate_golden_set.py

langfuse-check:
	python -c "from data_platform_rag.observability.langfuse_client import get_client; c = get_client(); print('Langfuse client type:', type(c).__name__)"

langfuse-flush:
	python -c "from data_platform_rag.observability.langfuse_client import get_client; get_client().flush(); print('flushed')"

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
