"""Process-wide singletons (embedded Qdrant allows only one client per data folder)."""

import logging
from functools import cached_property

from .config import Settings, get_settings
from .llm import LLM, LLMNotConfigured
from .retrieval.models import LocalModels
from .retrieval.retriever import Retriever
from .retrieval.store import VectorStore

log = logging.getLogger(__name__)


class Services:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @cached_property
    def local_models(self) -> LocalModels:
        return LocalModels(self.settings)

    @cached_property
    def store(self) -> VectorStore:
        return VectorStore(self.settings, self.local_models)

    @cached_property
    def retriever(self) -> Retriever:
        return Retriever(self.settings, self.store, self.local_models)

    def llm(self) -> LLM:
        """Raises LLMNotConfigured with a helpful message if no key is set."""
        return LLM(self.settings)

    def close(self) -> None:
        if "store" in self.__dict__:
            self.store.client.close()

    def llm_or_none(self) -> LLM | None:
        try:
            return self.llm()
        except LLMNotConfigured as exc:
            log.warning("LLM unavailable, continuing without it: %s", exc)
            return None


_services: Services | None = None


def get_services() -> Services:
    global _services
    if _services is None:
        _services = Services()
    return _services
