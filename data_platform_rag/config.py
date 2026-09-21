"""Runtime configuration for data-platform-rag. Per ADR-010, all env-derived config
lives here as a pydantic-settings singleton.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, PostgresDsn, SecretStr, ValidationError
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

    # Local models (no external cost)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"

    # Indexing. embedding_dim is the writer's dimension guard expectation and the
    # `chunks.embedding` column width, named once here so the two cannot drift.
    embedding_batch_size: int = Field(default=32, ge=1, le=512)
    embedding_dim: int = Field(default=384, ge=1)

    # Langfuse — optional, no-op if disabled
    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # Corpus sources (per AGENTS.md — two projects only)
    corpus_repo_snowflake: str = "https://github.com/christiandrocha/sdd-kafka-snowflake-2"
    corpus_repo_databricks: str = "https://github.com/christiandrocha/sdd-kafka-databricks"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton. Cached per process."""
    return Settings()


@lru_cache(maxsize=1)
def get_settings_without_llm() -> Settings:
    """Settings for a path that calls no LLM. Indexing is the whole audience.

    `anthropic_api_key` is required on `Settings`, and correctly so: generation
    cannot run without it. Indexing can -- it embeds locally with
    sentence-transformers and makes no Anthropic call at any point. Demanding
    the credential there fails a pipeline on something it never uses, which is
    what `ragas.yml` did for four runs, reporting it as a missing DATABASE_URL.

    The empty key is supplied only when the environment has none. Every other
    field is read from the environment exactly as usual, so a missing
    DATABASE_URL still fails here as loudly as it does in `get_settings`.

    Declared once, here, rather than per script: two copies of this fallback
    would be two places for the rule to drift.
    """
    try:
        return get_settings()
    except ValidationError:
        return Settings(anthropic_api_key="")
