# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Runtime configuration.

Model ids and endpoints live here and nowhere else, so swapping providers is a
config change rather than a code change.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings, prefixed ``GO2_``."""

    model_config = SettingsConfigDict(
        env_prefix="GO2_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://go2:go2@localhost:5433/go2"

    # Alibaba Model Studio, OpenAI-compatible surface.
    # Singapore endpoint: the Beijing one is cheaper but a different data
    # jurisdiction for company documents, and carries no free quota.
    dashscope_api_key: SecretStr = SecretStr("")
    dashscope_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    model_general: str = "qwen-plus"
    model_hard: str = "qwen3-max"
    model_ocr: str = "qwen-vl-ocr"

    # Where embedding and reranking run. "local" keeps every document on this
    # machine at the cost of saturating the CPU; "jina" sends document text and
    # queries to the API and leaves the machine idle. The invariant that
    # retrieval stays local holds only under "local", so this is opt-in.
    embedding_provider: Literal["local", "jina"] = "local"
    rerank_provider: Literal["local", "jina"] = "local"

    jina_api_key: SecretStr = SecretStr("")
    jina_embedding_model: str = "jina-embeddings-v5-text-small"  # 1024 dims, matches the column
    jina_rerank_model: str = "jina-reranker-v3.5"

    embedding_model: str = "electroglyph/Qwen3-Embedding-0.6B-onnx-uint8"
    embedding_dim: int = 1024
    # fastembed defaults to the system temp directory, which macOS purges --
    # losing 1.7 GB of weights and re-downloading them. Keep them somewhere
    # stable instead.
    model_cache_dir: Path = Path.home() / ".cache" / "go2" / "models"

    # Qwen3-Reranker is a causal LM scoring yes/no logits, not a cross-encoder,
    # so fastembed cannot serve it. This is the multilingual cross-encoder it
    # does support, and it handles Arabic queries against English passages.
    # fastembed defaults to 256, which on CPU buys nothing and costs a lot:
    # measured at 24 GB resident on a 59-chunk file, enough to swap-thrash a
    # 16 GB machine to a standstill. Throughput is flat from 1 to 4 and only
    # memory grows, so a small batch is strictly better here.
    embedding_batch_size: int = Field(default=4, ge=1, le=64)
    # Inference threads. Left unset, ONNX Runtime takes every core, which makes
    # a laptop unusable while a folder ingests. Half the cores keeps the machine
    # responsive and costs proportionally less throughput than it sounds,
    # because the work is memory-bandwidth bound as much as compute bound.
    inference_threads: int = Field(default=2, ge=1, le=64)

    reranker_model: str = "jinaai/jina-reranker-v2-base-multilingual"
    # How many fused candidates the cross-encoder scores. Reranking dominates
    # search latency, and cost is linear in candidates x characters, so these
    # two settings are the whole latency budget. Recall is already handled by
    # fusing two retrievers; the reranker only has to order what they found.
    rerank_candidates: int = Field(default=15, ge=1, le=200)
    # Characters of each passage shown to the cross-encoder. Measured cost is
    # ~0.2 ms/char/passage, so this is the single biggest latency lever.
    # Truncation applies only to the relevance judgement -- the full text is
    # still what gets returned and read.
    rerank_max_chars: int = Field(default=512, ge=64, le=8000)

    fernet_key: SecretStr = SecretStr("")
    google_client_secrets: Path = Path(".secrets/google_client_secret.json")

    langfuse_public_key: SecretStr = SecretStr("")
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_host: str = "https://cloud.langfuse.com"

    # Sized in characters, not tokens: the corpus is mixed Arabic/English and
    # a token budget from another model's tokenizer misestimates one script
    # badly. See go2.rag.chunking for the full reasoning.
    chunk_chars: int = Field(default=3200, ge=500, le=20000)
    chunk_overlap_chars: int = Field(default=400, ge=0, le=5000)

    @property
    def active_embedding_model(self) -> str:
        """Identifier of the model that produces vectors right now.

        Stored alongside every document so search can scope itself to vectors
        it can actually compare against.
        """
        if self.embedding_provider == "jina":
            return f"jina:{self.jina_embedding_model}"
        return self.embedding_model

    @property
    def langfuse_enabled(self) -> bool:
        """Whether both Langfuse keys are present."""
        return bool(
            self.langfuse_public_key.get_secret_value()
            and self.langfuse_secret_key.get_secret_value()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
