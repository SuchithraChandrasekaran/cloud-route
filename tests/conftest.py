"""Every test starts with embeddings off and no stored question, so a test that
calls main() cannot switch the real API on for the tests after it."""
import pytest

from agent import retrieval


@pytest.fixture(autouse=True)
def _retrieval_defaults(monkeypatch):
    monkeypatch.setattr(retrieval, "USE_EMBEDDINGS", False)
    monkeypatch.setattr(retrieval, "QUESTION", None)
