"""Finite operation budgets shared by Docker and HTTP adapters."""

from __future__ import annotations

import math
import time


class Deadline:
    """One finite wall-clock budget shared by every step of an operation."""

    def __init__(self, timeout_s: float):
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("A finite positive operation timeout is required")
        self.expires = time.monotonic() + timeout_s

    def remaining(self) -> float:
        remaining = self.expires - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Runtime operation deadline expired")
        return remaining
