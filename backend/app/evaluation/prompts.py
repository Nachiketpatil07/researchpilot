QUESTION = """You are writing a test set for a search system over research papers.

Paper: {title}
Passage (pages {pages}):
<passage>
{text}
</passage>

Write ONE question that a researcher might genuinely ask, which this passage answers.
Rules:
- The question must stand alone: name the method or paper topic (e.g. "In Self-RAG, ..."),
  never say "the passage", "this paper", "the authors" or "the table".
- Ask about an idea, mechanism, design choice or finding, not a single number from a table.
- Write a short reference answer (1-3 sentences) using only the passage.
- If the passage is mostly references, a table of numbers, an example prompt, or boilerplate,
  set "skip" to true.

Reply with a JSON object: {{"skip": false, "question": "...", "answer": "..."}}"""

VALIDATE = """You review questions for a test set about research papers.

Paper: {title}
Question: {question}
Reference answer: {answer}

Keep the question only if ALL are true:
1. It is about the paper's own research (its method, experiments, findings or design), not
   about example content quoted in an appendix (e.g. a sample essay, a demo prompt's topic)
   and not about a cited reference.
2. It stands alone: it does not point at "the passage", "this paper", a table or a figure.
3. It names the method/paper it is about, and that matches the paper above.

Reply with a JSON object: {{"keep": true or false, "reason": "short reason"}}"""

JUDGE = """You are grading an answer produced by a retrieval-augmented question answering system.

Question: {question}

Reference answer (written from the passage the question came from):
{reference}

Sources the system retrieved and could use:
{sources}

System answer:
{answer}

Score two things from 1 to 5:
- correctness: does the system answer convey the key facts of the reference answer?
  5 = all key facts, 3 = some, 1 = wrong or missing. An answer that says it could not
  find the information scores 1. Extra correct detail is fine.
- faithfulness: is every claim in the system answer supported by the retrieved sources?
  5 = fully supported, 3 = some unsupported claims, 1 = mostly unsupported.
  An answer that only says it could not find the information scores 5.

Reply with a JSON object: {{"correctness": n, "faithfulness": n, "note": "one short sentence"}}"""
