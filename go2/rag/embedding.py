# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Local embeddings via Qwen3 on ONNX.

Retrieval runs entirely on-device: no API key, no per-file cost, and no document
text leaving the machine. Only generation calls out.

Qwen3-Embedding is not in fastembed's built-in registry, so it is registered as
a custom model. The uint8 ONNX build must run with pooling disabled and
normalisation off -- the exported graph already performs last-token pooling, so
letting fastembed pool again would corrupt the vector.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import TYPE_CHECKING

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource as _ModelSource
from fastembed.common.model_description import PoolingType

from go2.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# Qwen3-Embedding is instruction-tuned: queries carry a task instruction while
# documents are embedded bare. Skipping this costs a few points of retrieval
# quality, so the asymmetry is deliberate and must be preserved.
QUERY_INSTRUCTION = (
    "Instruct: Given a question about the user's documents, "
    "retrieve the passages that answer it\nQuery: "
)

_ONNX_FILE = "dynamic_uint8.onnx"

_lock = threading.Lock()
_model: TextEmbedding | None = None
_registered = False


def _register(model_name: str, dim: int) -> None:
    global _registered  # noqa: PLW0603 -- fastembed's registry is process-global.
    if _registered:
        return
    try:
        TextEmbedding.add_custom_model(
            model=model_name,
            pooling=PoolingType.DISABLED,
            normalization=False,
            sources=_ModelSource(hf=model_name),
            dim=dim,
            model_file=_ONNX_FILE,
        )
    except ValueError:
        # Already registered in this process (fastembed raises on duplicates).
        logger.debug("model %s already registered", model_name)
    _registered = True


def get_model() -> TextEmbedding:
    """Return the process-wide embedding model, loading it on first use.

    Loading downloads roughly 600 MB on the first call and is therefore
    deliberately lazy: importing this module must stay cheap.
    """
    global _model  # noqa: PLW0603 -- one model per process; loading it twice doubles memory.
    with _lock:
        if _model is None:
            settings = get_settings()
            _register(settings.embedding_model, settings.embedding_dim)
            logger.info("loading embedding model %s", settings.embedding_model)
            settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
            _model = TextEmbedding(
                model_name=settings.embedding_model,
                cache_dir=str(settings.model_cache_dir),
            )
        return _model


def _normalise(vector: Sequence[float]) -> list[float]:
    """Scale a vector to unit length.

    The ONNX build emits unnormalised vectors. Normalising once at write time
    keeps stored vectors directly comparable and lets the index use either
    cosine or inner product without a second pass.
    """
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        return list(vector)
    return [component / norm for component in vector]


def embed_documents(texts: Sequence[str]) -> list[list[float]]:
    """Embed passages for storage.

    Args:
        texts: Chunk texts, in order.

    Returns:
        One unit-length vector per input, in the same order.
    """
    if not texts:
        return []
    # The batch size is bounded deliberately -- see Settings.embedding_batch_size.
    batch = get_settings().embedding_batch_size
    return [_normalise(v.tolist()) for v in get_model().embed(list(texts), batch_size=batch)]


def embed_query(text: str) -> list[float]:
    """Embed a search query.

    The instruction prefix is applied here and nowhere else, which is what makes
    query and document embeddings land in the same space for this model.

    Args:
        text: The user's question.

    Returns:
        A single unit-length vector.
    """
    vectors = list(get_model().embed([f"{QUERY_INSTRUCTION}{text}"]))
    return _normalise(vectors[0].tolist())
