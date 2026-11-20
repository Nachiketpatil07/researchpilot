"""Process-wide singletons (embedded Qdrant allows only one client per data folder)."""

import logging
import threading
from collections.abc import Callable
from typing import Any

from .config import Settings, get_settings
from .llm import LLM, LLMNotConfigured
from .retrieval.models import LocalModels
from .retrieval.retriever import Retriever
from .retrieval.store import VectorStore

log = logging.getLogger(__name__)


class Services:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        # FastAPI runs sync endpoints in a thread pool, so two requests can ask for a
        # lazy singleton at the same moment. Embedded Qdrant allows ONE client per
        # folder, so creation must happen exactly once: check-and-create under one lock.
        self._lock = threading.RLock()
        self._cache: dict[str, Any] = {}

    def _once(self, name: str, factory: Callable[[], Any]) -> Any:
        with self._lock:
            if name not in self._cache:
                self._cache[name] = factory()
            return self._cache[name]

    @property
    def local_models(self) -> LocalModels:
        return self._once("local_models", lambda: LocalModels(self.settings))

    @property
    def store(self) -> VectorStore:
        return self._once("store", lambda: VectorStore(self.settings, self.local_models))

    @property
    def retriever(self) -> Retriever:
        return self._once("retriever", lambda: Retriever(self.settings, self.store, self.local_models))

    def warm_up(self) -> None:
        """Open the store and load the models up front so the first request isn't slow."""
        _ = self.retriever
        _ = self.local_models.reranker

    def llm(self) -> LLM:
        """Raises LLMNotConfigured with a helpful message if no key is set."""
        return LLM(self.settings)

    def close(self) -> None:
        with self._lock:
            store = self._cache.pop("store", None)
        if store is not None:
            store.client.close()

    def llm_or_none(self) -> LLM | None:
        try:
            return self.llm()
        except LLMNotConfigured as exc:
            log.warning("LLM unavailable, continuing without it: %s", exc)
            return None


_services: Services | None = None
_services_lock = threading.Lock()


def get_services() -> Services:
    global _services
    with _services_lock:
        if _services is None:
            _services = Services()
    return _services
