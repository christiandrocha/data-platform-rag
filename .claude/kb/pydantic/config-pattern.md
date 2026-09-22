# Configuration with pydantic-settings

## The pattern

```python
# data_platform_rag/config.py
from functools import lru_cache
from pydantic import Field, SecretStr, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Reads from environment or .env."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    anthropic_api_key: SecretStr
    llm_model: str = "claude-sonnet-4-6"

    # Database
    database_url: PostgresDsn

    # Retrieval
    hybrid_top_k: int = Field(default=20, ge=1, le=100)
    rerank_top_k: int = Field(default=3, ge=1, le=20)
    fallback_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    hnsw_ef_search: int = Field(default=40, ge=10, le=500)

    # Models (local)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"

    # Langfuse (optional — disabled unless enabled=true and keys present)
    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()  # module-level convenience
```

## Why this pattern

- Single source of truth for all env-derived config
- Type-safe access everywhere — `settings.hybrid_top_k` not `os.getenv("HYBRID_TOP_K")`
- Validation at startup — misconfigured env fails loud, not silently later
- `SecretStr` prevents accidental log-leaking of API keys
- `PostgresDsn` validates the DSN format
- `@lru_cache` means the file is parsed once per process

## When a path does not use every required field

`anthropic_api_key` is required, so `get_settings()` raises for any process that
has no key — including indexing, which embeds locally and calls no LLM. That is
a real failure mode, not a hypothetical: `ragas.yml` failed on it for four runs
and reported it as a missing `DATABASE_URL`, because the caller's `except`
assumed the only thing that could be absent was the database.

`config.py` therefore exposes a second accessor:

```python
@lru_cache(maxsize=1)
def get_settings_without_llm() -> Settings:
    try:
        return get_settings()
    except ValidationError:
        return Settings(anthropic_api_key="")
```

The empty key is supplied only when the environment has none; every other field
is read from the environment as usual, so a missing `DATABASE_URL` still fails.
The indexing path (`indexer/embedder.py`, `scripts/index_corpus.py`) reads this
one. Anything that reaches generation reads `get_settings()` and must have a
real key.

Declared once, in `config.py`. A script that keeps its own copy of the fallback
is a second place for the rule to drift.

## Testing configuration

Tests use `monkeypatch.setenv(...)` to override. `Settings.model_rebuild()` is
NOT needed because `@lru_cache` isolates the singleton per process — pytest
gives us a fresh process per test session by default.
