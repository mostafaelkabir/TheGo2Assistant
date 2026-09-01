# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Runtime configuration.

Model ids and endpoints live here and nowhere else, so swapping providers is a
config change rather than a code change.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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

    # Retrieval runs on-device: no API, no cost, no data leaving the machine.
    embedding_model: str = "electroglyph/Qwen3-Embedding-0.6B-onnx-uint8"
    embedding_dim: int = 1024

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
