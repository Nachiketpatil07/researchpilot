"""Offline evaluation: synthetic test set, retrieval metrics, LLM-judged answer quality.

Results live in backend/eval/ (committed, so numbers in the README are reproducible).
"""

from ..config import BACKEND_DIR

EVAL_DIR = BACKEND_DIR / "eval"
TESTSET_PATH = EVAL_DIR / "testset.json"
RESULTS_DIR = EVAL_DIR / "results"
LATEST_PATH = RESULTS_DIR / "latest.json"
