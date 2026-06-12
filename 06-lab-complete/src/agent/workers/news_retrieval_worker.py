"""
NewsRetrievalWorker — Chuyên tìm kiếm trong tài liệu tin tức nghệ sĩ.

Pipeline:
  1. Semantic search (ChromaDB, filter type="news")
  2. Lexical search (BM25, chỉ corpus tin tức)
  3. RRF reranking gộp hai nguồn
  4. Trả về top_k chunks tin tức

Worker này chỉ nhìn thấy tin tức — không bị nhiễu bởi văn bản pháp luật.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ._retrieval_helpers import lexical_search_typed, semantic_search_typed
from .base_worker import BaseWorker, WorkerResult


class NewsRetrievalWorker(BaseWorker):
    """
    Retrieval Worker chuyên biệt cho tin tức nghệ sĩ liên quan đến ma tuý.
    Kết hợp dense search và sparse search trong domain tin tức.
    """
    name = "news_retrieval_worker"

    def run(self, query: str, top_k: int = 5, **kwargs) -> WorkerResult:
        try:
            from src.task7_reranking import rerank_rrf

            # 1. Dense retrieval — chỉ news
            dense = semantic_search_typed(query, doc_type="news", top_k=top_k * 2)

            # 2. Sparse retrieval — chỉ news
            sparse = lexical_search_typed(query, doc_type="news", top_k=top_k * 2)

            if not dense and not sparse:
                return self._success(
                    [],
                    doc_type="news",
                    dense_count=0,
                    sparse_count=0,
                    final_count=0,
                )

            # 3. RRF reranking
            ranked = rerank_rrf([dense, sparse], top_k=top_k)

            return self._success(
                ranked,
                doc_type="news",
                dense_count=len(dense),
                sparse_count=len(sparse),
                final_count=len(ranked),
            )

        except Exception as e:
            return self._error(str(e))
