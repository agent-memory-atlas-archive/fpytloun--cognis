"""Typed Intaris evaluation mode and staged-rollout default."""

from __future__ import annotations

from typing import Literal

IntarisEvaluation = Literal["legacy", "strict", "balanced", "bounded_autonomy"]
DEFAULT_INTARIS_EVALUATION: IntarisEvaluation = "balanced"
