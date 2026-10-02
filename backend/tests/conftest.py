"""Shared fixtures.

The retrieval tests import ``app.nodes.retriever``, which loads the persisted
Chroma store, the embedding model and a full-corpus BM25 index at import time.
That is expensive, so the model and retriever are session-scoped: the whole
suite pays for them once.

Tests that only need pure functions (title parsing, filter construction, fusion
math) must NOT import the retriever. See ``conftest``'s ``sys.path`` setup and
keep those modules free of heavy imports so they stay fast.
"""

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture(scope="session")
def corpus():
    """The processed corpus records, keyed by verse_id."""
    import json

    path = BACKEND / "processed" / "charaka_structured.json"
    if not path.is_file():
        pytest.skip("processed corpus missing; run scripts/transform.py")
    records = json.loads(path.read_text(encoding="utf-8"))
    return {r["verse_id"]: r for r in records}


@pytest.fixture(scope="session")
def retriever():
    """The imported retriever module (loads the model + index once)."""
    from app.nodes import retriever as module

    return module


@pytest.fixture(scope="session")
def titles():
    import json

    path = BACKEND / "reference" / "chapter_titles.json"
    if not path.is_file():
        pytest.skip("chapter titles missing; run scripts/build_chapter_titles.py")
    return json.loads(path.read_text(encoding="utf-8"))