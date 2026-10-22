"""lookup() with embeddings: off by default, hybrid when on, BM25 on failure."""
from agent import embed_retrieval as er
from agent import retrieval


def _fake_embed(texts):
    vocab = ["database", "dns", "cache", "address", "secret", "queue", "alert", "rollback"]
    return [[t.lower().count(w) + 0.01 for w in vocab] for t in texts]


def _on(monkeypatch, tmp_path, embed=_fake_embed):
    monkeypatch.setattr(retrieval, "USE_EMBEDDINGS", True)
    monkeypatch.setattr(er, "CACHE", str(tmp_path / "emb.json"))
    monkeypatch.setattr(er, "api_embed", embed)


def test_off_by_default():
    assert retrieval.USE_EMBEDDINGS is False


def test_off_means_bm25_and_no_embed_call(monkeypatch):
    def boom(texts):
        raise AssertionError("embedding API must not be called")
    monkeypatch.setattr(er, "api_embed", boom)
    out = retrieval.lookup("What happens if the service moves before its database?")
    assert out["passages"]


def test_on_returns_notes_with_ids(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    out = retrieval.lookup("dns cache address")
    assert out["passages"] and all(p["id"].startswith("fm-") for p in out["passages"])
    assert out["passages"][0]["id"] == "fm-04"


def test_on_tracks_returned_ids_for_citation_check(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    retrieval.reset_last()
    out = retrieval.lookup("dns cache address")
    first = out["passages"][0]["id"]
    assert retrieval.find_unreturned_citations(f"See [{first}].") == []


def test_on_off_topic_returns_no_note(monkeypatch, tmp_path):
    def far(texts):
        return [[1.0, 0, 0, 0, 0, 0, 0, 0] if "Instruct" in t else [0, 1.0, 0, 0, 0, 0, 0, 0] for t in texts]
    _on(monkeypatch, tmp_path, embed=far)
    out = retrieval.lookup("What is the capital of France?")
    assert out["passages"] == []


def test_embedding_failure_falls_back_to_bm25(monkeypatch, tmp_path):
    def down(texts):
        raise RuntimeError("network down")
    _on(monkeypatch, tmp_path, embed=down)
    out = retrieval.lookup("What happens if the service moves before its database?")
    assert out["passages"] and out["passages"][0]["id"] == "fm-01"


def test_custom_directory_always_uses_bm25(monkeypatch, tmp_path):
    def boom(texts):
        raise AssertionError("embedding API must not be called")
    _on(monkeypatch, tmp_path, embed=boom)
    from pathlib import Path
    real = Path(retrieval.NOTES_DIR)
    out = retrieval.lookup("What happens if the service moves before its database?", directory=real)
    assert out["passages"][0]["id"] == "fm-01"


def test_question_is_used_instead_of_a_shortened_topic(monkeypatch, tmp_path):
    seen = []

    def spy(texts):
        seen.extend(texts)
        return _fake_embed(texts)
    _on(monkeypatch, tmp_path, embed=spy)
    monkeypatch.setattr(retrieval, "QUESTION", "dns address cache that stays for hours")
    retrieval.lookup("short topic")
    assert any("dns address cache that stays for hours" in t for t in seen)
    assert not any("short topic" in t for t in seen)


def test_question_unset_uses_topic(monkeypatch, tmp_path):
    seen = []

    def spy(texts):
        seen.extend(texts)
        return _fake_embed(texts)
    _on(monkeypatch, tmp_path, embed=spy)
    monkeypatch.setattr(retrieval, "QUESTION", None)
    retrieval.lookup("dns cache address")
    assert any("dns cache address" in t for t in seen)
