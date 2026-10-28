"""R-14 structured RAG trace and metric normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RagTrace:
    run_id: str
    trace_id: str
    ticker: str
    trade_date: str
    strategy: str
    events: list[dict[str, Any]] = field(default_factory=list)

    def add_event(self, node: str, *, elapsed_ms: float, **values: Any) -> None:
        self.events.append({"node": node, "elapsed_ms": round(elapsed_ms, 3), **values})

    def summary(self) -> dict[str, Any]:
        elapsed = [float(event["elapsed_ms"]) for event in self.events]
        return {
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "strategy": self.strategy,
            "event_count": len(self.events),
            "total_elapsed_ms": round(sum(elapsed), 3),
            "token_in": sum(int(event.get("token_in", 0)) for event in self.events),
            "token_out": sum(int(event.get("token_out", 0)) for event in self.events),
            "errors": sum(1 for event in self.events if event.get("error_code")),
        }
