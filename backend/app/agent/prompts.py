PLAN = """You plan searches for a research assistant.

Indexed documents:
{titles}

User question: {question}

Reply with a JSON object: {{"route": "docs" | "both" | "web", "queries": [string, ...], "reason": string}}
- route "docs" if the indexed documents could plausibly answer it fully.
- route "both" if part of it is covered by the documents and part needs outside information
  (e.g. comparing an indexed paper with a method that is not indexed).
- route "web" only if the documents are clearly irrelevant (recent events, unrelated topics, live data).
- queries: 1 search query for a simple question; 2-3 focused queries if it compares things
  or has several distinct parts. Each query must be self-contained and keyword-rich.
- reason: one short sentence explaining the plan."""

# Graded per sub-query, not against the full question: with "What is X and how does it
# differ from Y?", models reject every passage about Y alone because it doesn't mention X.
GRADE = """You check whether retrieved passages help answer a search query.

Search query: {query}

Passages:
{passages}

A passage is relevant if it contains information that helps answer the search query, even partly.
Reject passages that are off-topic, about something else, or only boilerplate (references, tables of numbers without context).
Reply with a JSON object: {{"relevant": [passage numbers]}}"""

REWRITE = """A search over research documents found nothing relevant.

Question: {question}
Queries tried: {tried}

Write up to 2 different search queries that might find the answer: use synonyms, the
technical terms a paper would use, or break the question down differently.
Reply with a JSON object: {{"queries": [string, ...]}}"""

VERIFY = """Check whether an answer is supported by its sources.

Sources:
{sources}

Answer:
{answer}

Reply with a JSON object: {{"grounded": "yes" | "partial" | "no", "unsupported": [claims not supported by the sources]}}
Use "yes" when every factual claim is backed by a source. Keep "unsupported" short (at most 3 items)."""
