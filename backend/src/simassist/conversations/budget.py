"""Conservative heuristic, not exact provider token accounting.

UTF-8 bytes / 3 plus per-message framing; safety margin covers estimator
error and tool results. Tool schemas and system instructions are counted.
"""

import os
from dataclasses import dataclass
from math import ceil


def estimate(text: str) -> int:
    return ceil(len(text.encode("utf-8")) / 3) + 12


@dataclass(frozen=True)
class ContextBudget:
    window: int = 16384
    response: int = 768
    safety: int = 1536
    summary: int = 512
    auto_summary: bool = True

    @classmethod
    def from_env(cls):
        return cls(
            window=int(os.getenv("SIMASSIST_CONTEXT_WINDOW_TOKENS", "16384")),
            response=int(os.getenv("SIMASSIST_RESPONSE_RESERVE_TOKENS", "768")),
            safety=int(os.getenv("SIMASSIST_CONTEXT_SAFETY_MARGIN_TOKENS", "1536")),
            summary=int(os.getenv("SIMASSIST_SUMMARY_MAX_TOKENS", "512")),
            auto_summary=os.getenv("SIMASSIST_AUTO_SUMMARY", "true").lower()
            in ("true", "1", "yes"),
        )

    @property
    def available(self):
        if min(self.window, self.response, self.safety, self.summary) < 0:
            raise ValueError("Context budget settings must be nonnegative")
        return self.window - self.response - self.safety
