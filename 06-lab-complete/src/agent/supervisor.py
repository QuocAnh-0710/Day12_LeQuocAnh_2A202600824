"""
Supervisor — Điều phối toàn bộ pipeline theo pattern Supervisor-Workers.

Luồng xử lý:
  1. QueryAnalysisWorker: phân tích câu hỏi, quyết định routing
  2. [LegalRetrievalWorker] nếu routing bao gồm "legal_retrieval"
  3. [NewsRetrievalWorker]  nếu routing bao gồm "news_retrieval"
  4. RRF merge kết quả từ tất cả retrieval workers
  5. GenerationWorker: sinh câu trả lời có citation

Supervisor không thực hiện retrieval hay generation trực tiếp —
nó chỉ điều phối các Workers và tổng hợp kết quả.

              ┌─────────────────────────────────┐
              │           SUPERVISOR            │
              │  analyze → route → merge → gen  │
              └────────────┬────────────────────┘
                           │
         ┌─────────────────┼──────────────────┐
         ▼                 ▼                  ▼
  QueryAnalysis    LegalRetrieval      NewsRetrieval
    Worker           Worker              Worker
                         │                  │
                         └────────┬─────────┘
                                  ▼
                          GenerationWorker
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from .workers.generation_worker import GenerationWorker
from .workers.legal_retrieval_worker import LegalRetrievalWorker
from .workers.news_retrieval_worker import NewsRetrievalWorker
from .workers.query_analysis_worker import QueryAnalysisWorker


class Supervisor:
    """
    Điều phối các Workers để trả lời câu hỏi về pháp luật ma tuý và tin tức nghệ sĩ.

    Usage:
        supervisor = Supervisor()
        result = supervisor.run("Hình phạt tàng trữ heroin là bao nhiêu năm?")
        print(result["answer"])
        print(result["trace"])   # Full trace để debug / hiển thị
    """

    def __init__(self):
        self._workers = {
            "query_analysis": QueryAnalysisWorker(),
            "legal_retrieval": LegalRetrievalWorker(),
            "news_retrieval": NewsRetrievalWorker(),
            "generation": GenerationWorker(),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        query: str,
        top_k: int = 5,
        conversation_history: list[dict] | None = None,
    ) -> dict:
        """
        Chạy toàn bộ pipeline Supervisor-Workers.

        Args:
            query: Câu hỏi của người dùng
            top_k: Số chunks tối đa đưa vào generation
            conversation_history: Lịch sử hội thoại (list of {role, content})

        Returns:
            {
              "answer": str,
              "sources": list[dict],
              "analysis": dict,          # Output của QueryAnalysisWorker
              "retrieval_source": str,   # "legal" | "news" | "hybrid"
              "trace": list[dict],       # Trace từng worker để debug
            }
        """
        trace = []

        # ── Step 1: Phân tích câu hỏi ──────────────────────────────────
        analysis_result = self._workers["query_analysis"].run(query=query)
        trace.append(self._format_trace(analysis_result))

        if analysis_result.status == "error":
            # Fallback: tìm khắp nơi
            analysis = {
                "type": "both",
                "routing": ["legal_retrieval", "news_retrieval"],
                "entities": [],
                "intent": query,
            }
        else:
            analysis = analysis_result.data

        routing: list[str] = analysis.get("routing", ["legal_retrieval", "news_retrieval"])

        # ── Step 2: Retrieval workers theo routing ──────────────────────
        retrieval_results: dict[str, list[dict]] = {}

        for worker_name in routing:
            if worker_name not in self._workers:
                continue
            worker_result = self._workers[worker_name].run(
                query=query,
                top_k=top_k,
            )
            trace.append(self._format_trace(worker_result))
            if worker_result.status in ("success", "error"):
                retrieval_results[worker_name] = worker_result.data or []

        # ── Step 3: Merge kết quả từ các retrieval workers ─────────────
        all_chunks = self._merge_retrieval_results(retrieval_results, top_k=top_k)

        retrieval_source = self._determine_retrieval_source(routing, all_chunks)

        # ── Step 4: Generation ──────────────────────────────────────────
        gen_result = self._workers["generation"].run(
            query=query,
            chunks=all_chunks,
            conversation_history=conversation_history,
        )
        trace.append(self._format_trace(gen_result))

        gen_data = gen_result.data or {}

        return {
            "answer": gen_data.get("answer", "Đã xảy ra lỗi trong quá trình xử lý."),
            "sources": gen_data.get("sources", all_chunks),
            "analysis": analysis,
            "retrieval_source": retrieval_source,
            "trace": trace,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _merge_retrieval_results(
        self,
        results_by_worker: dict[str, list[dict]],
        top_k: int,
    ) -> list[dict]:
        """
        Gộp kết quả từ nhiều retrieval workers dùng RRF.

        Nếu chỉ có 1 worker → trả thẳng kết quả của worker đó.
        Nếu có nhiều worker → RRF merge để kết hợp tín hiệu legal + news.
        """
        non_empty = [chunks for chunks in results_by_worker.values() if chunks]

        if not non_empty:
            return []

        if len(non_empty) == 1:
            return non_empty[0][:top_k]

        # RRF merge tất cả ranked lists
        from src.task7_reranking import rerank_rrf

        return rerank_rrf(non_empty, top_k=top_k)

    def _determine_retrieval_source(
        self, routing: list[str], chunks: list[dict]
    ) -> str:
        """Xác định nhãn retrieval source để hiển thị trên UI."""
        if not chunks:
            return "none"
        if len(routing) > 1:
            return "hybrid (legal + news)"
        return routing[0].replace("_retrieval", "") if routing else "unknown"

    @staticmethod
    def _format_trace(worker_result) -> dict:
        """Chuẩn hoá trace entry từ WorkerResult để hiển thị."""
        return {
            "worker": worker_result.worker_name,
            "status": worker_result.status,
            "error": worker_result.error,
            **worker_result.trace,
        }
