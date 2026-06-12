"""
LegalRetrievalWorker — Chuyên tìm kiếm trong tài liệu pháp luật.

Pipeline:
  1. Semantic search (ChromaDB, filter type="legal")
  2. Lexical search (BM25, chỉ corpus pháp luật)
  3. RRF reranking gộp hai nguồn
  4. Trả về top_k chunks pháp luật

Worker này chỉ nhìn thấy tài liệu pháp luật — không bị nhiễu bởi tin tức.
"""

from ._retrieval_helpers import lexical_search_typed, semantic_search_typed
from .base_worker import BaseWorker, WorkerResult

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


class LegalRetrievalWorker(BaseWorker):
    """
    Retrieval Worker chuyên biệt cho tài liệu pháp luật.
    Kết hợp dense search và sparse search trong domain pháp luật.
    """
    name = "legal_retrieval_worker"

    def run(self, query: str, top_k: int = 5, **kwargs) -> WorkerResult:
        try:
            from src.task7_reranking import rerank_rrf

            # 1. Dense retrieval — chỉ legal
            dense = semantic_search_typed(query, doc_type="legal", top_k=top_k * 2)

            # 2. Sparse retrieval — chỉ legal
            sparse = lexical_search_typed(query, doc_type="legal", top_k=top_k * 2)

            if not dense and not sparse:
                return self._success(
                    [],
                    doc_type="legal",
                    dense_count=0,
                    sparse_count=0,
                    final_count=0,
                )

            # 3. RRF reranking
            ranked = rerank_rrf([dense, sparse], top_k=top_k)

            return self._success(
                ranked,
                doc_type="legal",
                dense_count=len(dense),
                sparse_count=len(sparse),
                final_count=len(ranked),
            )

        except Exception as e:
            return self._error(str(e))
