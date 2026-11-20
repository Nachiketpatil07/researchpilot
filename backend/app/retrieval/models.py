"""Local embedding + reranking models (CPU, ONNX via fastembed). Loaded once, lazily."""

import os
from functools import cached_property

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # harmless on Windows
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

from fastembed import SparseTextEmbedding, TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from ..config import Settings


class LocalModels:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.models_cache.mkdir(parents=True, exist_ok=True)
        self._cache = str(settings.models_cache)

    @cached_property
    def dense(self) -> TextEmbedding:
        return TextEmbedding(self.settings.dense_model, cache_dir=self._cache)

    @cached_property
    def sparse(self) -> SparseTextEmbedding:
        return SparseTextEmbedding(self.settings.sparse_model, cache_dir=self._cache)

    @cached_property
    def reranker(self) -> TextCrossEncoder:
        return TextCrossEncoder(self.settings.rerank_model, cache_dir=self._cache)

    @cached_property
    def dense_dim(self) -> int:
        return len(next(iter(self.dense.embed(["dimension probe"]))))
