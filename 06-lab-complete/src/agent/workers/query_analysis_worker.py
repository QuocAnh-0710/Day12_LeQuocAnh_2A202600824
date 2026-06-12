"""
QueryAnalysisWorker — Phân tích câu hỏi và quyết định routing.

Hai bước:
  1. Thử dùng LLM (Groq) để phân tích chính xác (có API key).
  2. Fallback sang bộ phân loại keyword nếu không có key.

Output schema:
  {
    "type": "legal" | "news" | "both",
    "routing": ["legal_retrieval"] | ["news_retrieval"] | ["legal_retrieval", "news_retrieval"],
    "entities": [str, ...],          # Tên người, điều luật, năm...
    "intent": str,                   # Mô tả ngắn ý định câu hỏi
    "method": "llm" | "keyword"      # Phương pháp phân loại đã dùng
  }
"""

import json
import os
import re

from .base_worker import BaseWorker, WorkerResult

# Từ khoá đặc trưng cho từng domain
_LEGAL_KEYWORDS = [
    "điều", "luật", "nghị định", "khoản", "hình phạt", "phạt tù",
    "tội", "phạt tiền", "bộ luật", "quy định", "nghiêm cấm",
    "cai nghiện", "bắt buộc", "xử lý", "hành chính", "hình sự",
    "truy tố", "khởi tố", "tạm giam", "thi hành", "án phạt",
]
_NEWS_KEYWORDS = [
    "nghệ sĩ", "ca sĩ", "rapper", "diễn viên", "người mẫu",
    "bị bắt", "bị truy tố", "bị khởi tố", "bị tạm giam",
    "chi dân", "miu lê", "bình gold", "sơn ngọc minh", "long nhật",
    "tin tức", "vụ án", "scandal", "bắt giữ", "triệt phá",
]

_ANALYSIS_PROMPT = """Phân tích câu hỏi sau và trả về JSON (không có markdown, chỉ JSON thuần):

Câu hỏi: {query}

Trả về JSON với schema:
{{
  "type": "legal" hoặc "news" hoặc "both",
  "routing": danh sách gồm "legal_retrieval" và/hoặc "news_retrieval",
  "entities": danh sách tên người, điều luật, số nghị định, năm... xuất hiện trong câu hỏi,
  "intent": mô tả ngắn gọn (1 câu) ý định của câu hỏi
}}

Quy tắc phân loại:
- "legal": câu hỏi về điều luật, hình phạt, quy định pháp luật, nghị định
- "news": câu hỏi về nghệ sĩ, người nổi tiếng, vụ bắt giữ cụ thể, tin tức
- "both": câu hỏi kết hợp cả pháp lý lẫn tin tức, hoặc không rõ ràng"""


class QueryAnalysisWorker(BaseWorker):
    """
    Worker phân tích câu hỏi, trích xuất thực thể và quyết định
    routing tới các retrieval workers phù hợp.
    """
    name = "query_analysis_worker"

    def run(self, query: str, **kwargs) -> WorkerResult:
        # Thử LLM trước
        api_key = os.getenv("GROQ_API_KEY", "")
        if api_key:
            result = self._analyze_with_llm(query, api_key)
            if result is not None:
                return self._success(result, method="llm", query=query)

        # Fallback: keyword classifier
        result = self._analyze_with_keywords(query)
        return self._success(result, method="keyword", query=query)

    # ------------------------------------------------------------------
    # LLM-based analysis
    # ------------------------------------------------------------------

    def _analyze_with_llm(self, query: str, api_key: str) -> dict | None:
        try:
            from groq import Groq

            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                max_tokens=256,
                temperature=0.0,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Bạn là bộ phân loại câu hỏi. "
                            "Chỉ trả về JSON thuần, không thêm bất kỳ text nào khác."
                        ),
                    },
                    {"role": "user", "content": _ANALYSIS_PROMPT.format(query=query)},
                ],
            )
            raw = response.choices[0].message.content.strip()
            # Trích JSON từ response (phòng trường hợp LLM thêm markdown)
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                return self._validate_and_fix(parsed)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Keyword-based fallback
    # ------------------------------------------------------------------

    def _analyze_with_keywords(self, query: str) -> dict:
        q = query.lower()
        legal_hits = [kw for kw in _LEGAL_KEYWORDS if kw in q]
        news_hits = [kw for kw in _NEWS_KEYWORDS if kw in q]

        if legal_hits and not news_hits:
            doc_type = "legal"
            routing = ["legal_retrieval"]
        elif news_hits and not legal_hits:
            doc_type = "news"
            routing = ["news_retrieval"]
        else:
            doc_type = "both"
            routing = ["legal_retrieval", "news_retrieval"]

        entities = self._extract_entities_simple(query)

        return {
            "type": doc_type,
            "routing": routing,
            "entities": entities,
            "intent": f"Câu hỏi về {doc_type} liên quan đến: {', '.join(entities) or 'ma tuý'}",
        }

    def _extract_entities_simple(self, query: str) -> list[str]:
        """Trích thực thể đơn giản: điều luật, năm, tên viết hoa."""
        entities = []
        # Số điều luật: "Điều 249", "Điều 251"
        for m in re.finditer(r"[Đđ]iều\s+\d+", query):
            entities.append(m.group())
        # Năm: 2021, 2023...
        for m in re.finditer(r"\b(19|20)\d{2}\b", query):
            entities.append(m.group())
        # Từ viết hoa (tên người): "Chi Dân", "Miu Lê"
        for m in re.finditer(r"\b[A-ZÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÉÈẺẼẸÊẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÚÙỦŨỤƯỨỪỬỮỰÝỲỶỸỴĐĐ][a-záàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]+(?:\s+[A-ZÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÉÈẺẼẸÊẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÚÙỦŨỤƯỨỪỬỮỰÝỲỶỸỴĐ][a-záàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]+)+\b", query):
            entities.append(m.group())
        return list(dict.fromkeys(entities))  # deduplicate, preserve order

    def _validate_and_fix(self, parsed: dict) -> dict:
        """Đảm bảo output của LLM đúng schema."""
        valid_types = {"legal", "news", "both"}
        if parsed.get("type") not in valid_types:
            parsed["type"] = "both"

        valid_workers = {"legal_retrieval", "news_retrieval"}
        routing = parsed.get("routing", [])
        if not isinstance(routing, list) or not all(r in valid_workers for r in routing):
            parsed["routing"] = (
                ["legal_retrieval"] if parsed["type"] == "legal"
                else ["news_retrieval"] if parsed["type"] == "news"
                else ["legal_retrieval", "news_retrieval"]
            )

        if not isinstance(parsed.get("entities"), list):
            parsed["entities"] = []

        if not isinstance(parsed.get("intent"), str):
            parsed["intent"] = ""

        return parsed
