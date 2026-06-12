"""
GenerationWorker — Sinh câu trả lời có citation từ context đã retrieve.

Pipeline:
  1. Nhận merged chunks từ Supervisor
  2. Áp dụng "lost in the middle" reordering (Liu et al. 2023)
  3. Format context với source labels
  4. Gọi LLM (Groq Llama) với system prompt yêu cầu citation
  5. Trả về answer + sources

Worker này chỉ tập trung vào generation — không làm retrieval.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from .base_worker import BaseWorker, WorkerResult

TEMPERATURE = 0.3
MAX_TOKENS = 1024

SYSTEM_PROMPT = """Trả lời câu hỏi bằng tiếng Việt một cách toàn diện và chính xác.
Với mỗi thông tin, ngay lập tức chèn citation trong ngoặc vuông dẫn đến nguồn cụ thể
(ví dụ: [Luật Phòng chống ma tuý 2021, Điều 3] hoặc [VnExpress, 2024]).

Nếu thông tin không có trong context được cung cấp, hãy nói:
'Tôi không thể xác minh thông tin này từ nguồn hiện có' thay vì đoán.

Quy tắc:
- Chỉ dùng thông tin từ context được cung cấp
- Mọi thông tin thực tế PHẢI có citation
- Nếu context không đủ, nói rõ
- Trả lời có cấu trúc rõ ràng"""


def _reorder_for_llm(chunks: list[dict]) -> list[dict]:
    """
    Sắp xếp tránh "lost in the middle": quan trọng nhất ở đầu và cuối,
    ít quan trọng nhất ở giữa.
    """
    if len(chunks) <= 2:
        return chunks
    first_half = chunks[::2]
    second_half = chunks[1::2][::-1]
    return first_half + second_half


def _format_context(chunks: list[dict]) -> str:
    """Format chunks thành context string có source labels để LLM cite."""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        meta = chunk.get("metadata", {})
        source = meta.get("source", f"Source {i}").replace(".md", "").replace(".docx", "")
        doc_type = meta.get("type", "unknown")
        parts.append(
            f"[Tài liệu {i} | Nguồn: {source} | Loại: {doc_type}]\n{chunk['content']}"
        )
    return "\n\n---\n\n".join(parts)


class GenerationWorker(BaseWorker):
    """
    Worker sinh câu trả lời có citation từ danh sách chunks đã retrieve.
    Sử dụng Groq Llama 3.1 nếu có API key.
    """
    name = "generation_worker"

    def run(
        self,
        query: str,
        chunks: list[dict],
        conversation_history: list[dict] | None = None,
        **kwargs,
    ) -> WorkerResult:
        if not chunks:
            return self._success(
                {
                    "answer": "Tôi không thể xác minh thông tin này từ nguồn hiện có.",
                    "sources": [],
                },
                chunks_used=0,
            )

        # Reorder + format
        reordered = _reorder_for_llm(chunks)
        context = _format_context(reordered)

        # Build user message với conversation history nếu có
        history_str = ""
        if conversation_history:
            recent = conversation_history[-4:]  # tối đa 2 lượt Q+A
            lines = []
            for m in recent:
                if m["role"] == "user":
                    lines.append(f"Q: {m['content']}")
                elif m["role"] == "assistant":
                    lines.append(f"A: {m['content'][:200]}...")
            if lines:
                history_str = "[Ngữ cảnh hội thoại]\n" + "\n".join(lines) + "\n\n"

        user_message = (
            f"{history_str}"
            f"Context:\n{context}\n\n"
            f"---\n\n"
            f"Câu hỏi: {query}"
        )

        # Gọi LLM
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            return self._success(
                {
                    "answer": (
                        "GROQ_API_KEY chưa được set. Thêm key vào file .env.\n\n"
                        "Context đã retrieve:\n\n" + context[:500] + "..."
                    ),
                    "sources": chunks,
                },
                chunks_used=len(chunks),
                llm_called=False,
            )

        try:
            from groq import Groq

            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
            answer = response.choices[0].message.content

            return self._success(
                {"answer": answer, "sources": chunks},
                chunks_used=len(chunks),
                llm_called=True,
                model="llama-3.1-8b-instant",
            )

        except Exception as e:
            return self._error(
                str(e),
                data={
                    "answer": f"[Generation error: {e}]\n\nContext:\n{context[:600]}",
                    "sources": chunks,
                },
            )
