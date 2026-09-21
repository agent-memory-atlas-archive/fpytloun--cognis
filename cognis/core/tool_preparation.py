"""Per-generation limits for streamed tool input, before any execution."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolPreparationBudget:
    """Bound continuously active preparation independently of idle timeouts."""

    max_seconds: float = 600
    max_chars: int = 262_144
    started_at: float | None = None
    input_sizes: dict[str, int] = field(default_factory=dict)

    def observe(self, call_id: str, input_chars: int, now: float) -> str | None:
        """Return a safe failure reason when the generation exceeds its budget."""
        if self.started_at is None:
            self.started_at = now
        self.input_sizes[call_id] = max(input_chars, self.input_sizes.get(call_id, 0))
        if sum(self.input_sizes.values()) > self.max_chars:
            return "Tool input generation exceeded the 262144-character preparation limit"
        if now - self.started_at >= self.max_seconds:
            return "Tool input generation exceeded the 600-second preparation limit"
        return None
