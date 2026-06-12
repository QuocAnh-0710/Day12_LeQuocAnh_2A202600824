"""
Base class cho tất cả Workers trong pattern Supervisor-Workers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkerResult:
    """Kết quả trả về từ một Worker."""
    worker_name: str
    status: str           # "success" | "error" | "skipped"
    data: Any             # Payload chính
    error: str = None     # Thông báo lỗi nếu status == "error"
    trace: dict = field(default_factory=dict)  # Metadata để debug


class BaseWorker(ABC):
    """Abstract base class — mỗi Worker phải implement run()."""
    name: str = "base_worker"

    @abstractmethod
    def run(self, **kwargs) -> WorkerResult:
        """Thực thi công việc của worker và trả về WorkerResult."""
        ...

    def _success(self, data: Any, **trace_kwargs) -> WorkerResult:
        return WorkerResult(
            worker_name=self.name,
            status="success",
            data=data,
            trace={"worker": self.name, **trace_kwargs},
        )

    def _error(self, error: str, data: Any = None) -> WorkerResult:
        return WorkerResult(
            worker_name=self.name,
            status="error",
            data=data or [],
            error=error,
            trace={"worker": self.name, "error": error},
        )

    def _skipped(self, reason: str) -> WorkerResult:
        return WorkerResult(
            worker_name=self.name,
            status="skipped",
            data=[],
            trace={"worker": self.name, "skipped_reason": reason},
        )
