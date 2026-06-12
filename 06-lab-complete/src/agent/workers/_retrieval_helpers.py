"""
Helpers dùng chung cho LegalRetrievalWorker và NewsRetrievalWorker.

Cung cấp semantic_search và lexical_search được lọc theo doc_type
("legal" hoặc "news") để mỗi worker chỉ tìm trong domain của mình.
"""

from pathlib import Path

_CHROMA_DIR = Path(__file__).parent.parent.parent.parent / "data" / "chroma_db"
_CORPUS_FILE = Path(__file__).parent.parent.parent.parent / "data" / "corpus.json"
_COLLECTION_NAME = "DrugLawDocs"
_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Module-level cache cho collection và corpus
_collection = None
_corpus_by_type: dict[str, list[dict]] = {}
_bm25_by_type: dict = {}


def _get_collection():
    global _collection
    if _collection is None:
        import chromadb
        from chromadb.utils import embedding_functions

        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=_EMBEDDING_MODEL
        )
        _collection = client.get_collection(name=_COLLECTION_NAME, embedding_function=ef)
    return _collection


def semantic_search_typed(query: str, doc_type: str, top_k: int = 10) -> list[dict]:
    """
    Tìm kiếm ngữ nghĩa chỉ trong documents thuộc doc_type.

    Args:
        query: Câu truy vấn
        doc_type: "legal" hoặc "news"
        top_k: Số kết quả tối đa

    Returns:
        List of {'content': str, 'score': float, 'metadata': dict}
    """
    collection = _get_collection()
    total = collection.count()
    if total == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=min(top_k * 2, total),  # lấy nhiều hơn để bù sau filter
        where={"type": doc_type},
        include=["documents", "metadatas", "distances"],
    )

    output = []
    if results["documents"] and results["documents"][0]:
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            score = max(0.0, 1.0 - dist)
            output.append({"content": doc, "score": round(score, 4), "metadata": meta or {}})

    output.sort(key=lambda x: x["score"], reverse=True)
    return output[:top_k]


def lexical_search_typed(query: str, doc_type: str, top_k: int = 10) -> list[dict]:
    """
    BM25 search chỉ trong documents thuộc doc_type.
    Index được cache theo type để tái sử dụng.

    Args:
        query: Câu truy vấn
        doc_type: "legal" hoặc "news"
        top_k: Số kết quả tối đa

    Returns:
        List of {'content': str, 'score': float, 'metadata': dict}
    """
    import json

    import numpy as np
    from rank_bm25 import BM25Okapi

    global _corpus_by_type, _bm25_by_type

    # Build or retrieve cached BM25 index for this doc_type
    if doc_type not in _bm25_by_type:
        if not _CORPUS_FILE.exists():
            return []

        full_corpus: list[dict] = json.loads(_CORPUS_FILE.read_text(encoding="utf-8"))
        filtered = [
            c for c in full_corpus
            if c.get("metadata", {}).get("type") == doc_type
        ]

        if not filtered:
            return []

        _corpus_by_type[doc_type] = filtered
        tokenized = [doc["content"].lower().split() for doc in filtered]
        _bm25_by_type[doc_type] = BM25Okapi(tokenized, k1=1.5, b=0.75)

    bm25 = _bm25_by_type[doc_type]
    corpus = _corpus_by_type[doc_type]

    scores = bm25.get_scores(query.lower().split())
    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []
    for idx in top_indices:
        if scores[idx] > 0:
            results.append({
                "content": corpus[idx]["content"],
                "score": float(scores[idx]),
                "metadata": corpus[idx].get("metadata", {}),
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]
