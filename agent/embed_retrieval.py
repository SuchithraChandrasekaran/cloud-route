"""Embedding retrieval over the failure-mode notes (Qwen3-Embedding-8B on Nebius).

Sits beside agent/retrieval.py (BM25), which it does not change.
Note vectors are cached in docs/failure-modes/.embeddings.json and rebuilt only
when a note's text changes. Only the question is sent to the API at query time.
"""
import hashlib
import json
import math
import os

from agent.retrieval import search as bm25_search

MODEL = os.environ.get("NEBIUS_EMBED_MODEL", "Qwen/Qwen3-Embedding-8B")
BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "failure-modes", ".embeddings.json")
TASK = "Given a question about a cloud migration, find the guidance note that answers it"


def _g(n, key):
    """Read a field from a note whether it is a dict or an object."""
    return n[key] if isinstance(n, dict) else getattr(n, key)


def _note_text(n):
    return f"{_g(n, 'title')}. {_g(n, 'text')}"


def _query_text(q):
    return f"Instruct: {TASK}\nQuery: {q}"


def api_embed(texts):
    from openai import OpenAI
    client = OpenAI(base_url=BASE_URL, api_key=os.environ["NEBIUS_API_KEY"])
    out = client.embeddings.create(model=MODEL, input=texts)
    return [d.embedding for d in sorted(out.data, key=lambda d: d.index)]


def _cos(a, b):
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def build_index(notes, embed=None, cache=None):
    """Return {note id: vector}. Reuses cached vectors whose text hash matches."""
    embed = embed or api_embed
    cache = cache or CACHE
    try:
        cached = json.load(open(cache))
    except (OSError, ValueError):
        cached = {}
    if cached.get("model") != MODEL:
        cached = {}
    vecs, todo = {}, []
    for n in notes:
        h = hashlib.sha256(_note_text(n).encode()).hexdigest()
        hit = cached.get("notes", {}).get(_g(n, "id"))
        if hit and hit["hash"] == h:
            vecs[_g(n, "id")] = hit
        else:
            todo.append((n, h))
    if todo:
        for (n, h), v in zip(todo, embed([_note_text(n) for n, _ in todo])):
            vecs[_g(n, "id")] = {"hash": h, "vec": v}
        try:
            json.dump({"model": MODEL, "notes": vecs}, open(cache, "w"))
        except OSError:
            pass
    return {i: v["vec"] for i, v in vecs.items()}


def search_embed(query, notes, index, embed=None, k=3, min_score=0.0):
    """Top-k (note, cosine) pairs with score >= min_score, best first."""
    embed = embed or api_embed
    qv = embed([_query_text(query)])[0]
    scored = sorted(((n, _cos(qv, index[_g(n, "id")])) for n in notes), key=lambda t: -t[1])
    return [(n, s) for n, s in scored[:k] if s >= min_score]


def search_hybrid(query, notes, index, embed=None, k=3, min_score=0.0, c=60):
    """Reciprocal-rank fusion of BM25 and embedding ranks.

    A note must pass the embedding score floor, so out-of-scope questions still
    return nothing even when a stray word matches in BM25."""
    emb = search_embed(query, notes, index, embed=embed, k=len(notes), min_score=min_score)
    if not emb:
        return []
    ers = {_g(n, "id"): i for i, (n, _) in enumerate(emb)}
    brs = {}
    for i, r in enumerate(bm25_search(query, notes)):
        n = r[0] if isinstance(r, (tuple, list)) else r
        n = n.get("note", n) if isinstance(n, dict) else getattr(n, "note", n)
        brs[_g(n, "id")] = i
    fused = {}
    for nid, rank in ers.items():
        fused[nid] = 1 / (c + rank) + (1 / (c + brs[nid]) if nid in brs else 0)
    by_id = {_g(n, "id"): n for n in notes}
    return [(by_id[i], s) for i, s in sorted(fused.items(), key=lambda t: -t[1])[:k]]
