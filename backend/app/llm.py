"""Provider-agnostic LLM client.

Groq, Gemini and Ollama all expose OpenAI-compatible endpoints, so one client
covers all three. Switch providers with LLM_PROVIDER in .env.
"""

import json
import re
from collections.abc import Iterator

from openai import BadRequestError, OpenAI

from .config import Settings

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_field": "groq_api_key",
        # Groq rotates its catalog; list current ids with client.models.list().
        "answer": "openai/gpt-oss-120b",
        "fast": "openai/gpt-oss-20b",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_field": "gemini_api_key",
        "answer": "gemini-2.5-flash",
        "fast": "gemini-2.5-flash-lite",
    },
    "ollama": {
        "base_url": None,  # taken from settings.ollama_base_url
        "key_field": None,
        "answer": "llama3.2",
        "fast": "llama3.2",
    },
}


class LLMNotConfigured(RuntimeError):
    pass


def parse_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)  # tolerate prose/code fences
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Model did not return JSON: {text[:200]!r}")


class LLM:
    def __init__(self, settings: Settings):
        provider = settings.llm_provider.lower()
        if provider not in PROVIDERS:
            raise LLMNotConfigured(
                f"Unknown LLM_PROVIDER '{provider}'. Use one of: {', '.join(PROVIDERS)}"
            )
        spec = PROVIDERS[provider]
        if spec["key_field"]:
            api_key = getattr(settings, spec["key_field"])
            if not api_key:
                raise LLMNotConfigured(
                    f"{spec['key_field'].upper()} is empty. Add it to backend/.env."
                )
        else:
            api_key = "ollama"
        base_url = spec["base_url"] or settings.ollama_base_url

        self.provider = provider
        self.models = {
            "answer": settings.answer_model or spec["answer"],
            "fast": settings.fast_model or spec["fast"],
        }
        # max_retries makes the SDK back off on 429s, which free tiers hit often.
        self.client = OpenAI(base_url=base_url, api_key=api_key, max_retries=4, timeout=60)

    def _is_reasoning(self, model: str) -> bool:
        return "gpt-oss" in model

    def _kwargs(self, tier: str, temperature: float, max_tokens: int) -> dict:
        model = self.models[tier]
        kw = {"model": model, "temperature": temperature, "max_tokens": max_tokens}
        if self._is_reasoning(model):
            # Reasoning models spend tokens thinking before answering: keep effort low and
            # leave headroom so short replies (summaries, grades) don't come back empty.
            kw["max_tokens"] = max(max_tokens + 1024, 1536)
            if self.provider == "groq":
                kw["extra_body"] = {"reasoning_effort": "low"}
        return kw

    def complete(
        self,
        messages: list[dict],
        tier: str = "answer",
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        resp = self.client.chat.completions.create(
            messages=messages, **self._kwargs(tier, temperature, max_tokens)
        )
        return (resp.choices[0].message.content or "").strip()

    def complete_json(self, messages: list[dict], tier: str = "fast", max_tokens: int = 400) -> dict:
        """Ask for a JSON object (prompts must mention JSON). Raises ValueError if unparseable."""
        kw = self._kwargs(tier, 0.0, max_tokens)
        try:
            resp = self.client.chat.completions.create(
                messages=messages, response_format={"type": "json_object"}, **kw
            )
        except BadRequestError:  # provider/model without JSON mode, or failed validation
            resp = self.client.chat.completions.create(messages=messages, **kw)
        return parse_json(resp.choices[0].message.content or "")

    def stream(
        self,
        messages: list[dict],
        tier: str = "answer",
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        stream = self.client.chat.completions.create(
            messages=messages, stream=True, **self._kwargs(tier, temperature, max_tokens)
        )
        for event in stream:
            if event.choices and event.choices[0].delta.content:
                yield event.choices[0].delta.content
