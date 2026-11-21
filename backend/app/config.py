from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM
    llm_provider: str = "groq"  # groq | gemini | ollama
    groq_api_key: str = ""
    gemini_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434/v1"
    answer_model: str = ""  # empty -> provider default
    fast_model: str = ""

    # Local models (all run on CPU via fastembed / ONNX)
    dense_model: str = "BAAI/bge-small-en-v1.5"
    sparse_model: str = "Qdrant/bm25"
    # Chosen by `python -m app.cli eval-rerankers`: best quality/latency on CPU.
    # Use Xenova/ms-marco-MiniLM-L-6-v2 for ~2x faster reranking at lower accuracy.
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-12-v2"

    # Storage
    # Index, model cache, uploads and samples. Kept on a short path by default because
    # model caches and Qdrant files nest deeply (Windows 260-char path limit).
    data_dir: Path = Path.home() / ".researchpilot"
    collection: str = "researchpilot"

    # Ingestion
    chunk_size: int = 1200  # characters
    chunk_overlap: int = 200
    context_mode: str = "header"  # off | header | full

    # Retrieval
    retrieve_k: int = 20  # candidates from each retriever before reranking (CPU cost scales with this)
    rerank_top_n: int = 6  # chunks passed to the LLM

    @property
    def qdrant_path(self) -> Path:
        return self.data_dir / "qdrant"

    @property
    def models_cache(self) -> Path:
        return self.data_dir / "models"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def samples_dir(self) -> Path:
        return self.data_dir / "samples"


@lru_cache
def get_settings() -> Settings:
    return Settings()
