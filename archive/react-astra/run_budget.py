"""Token and wall-time budget for one agent run, with a reserved tail.

The reserve (time and tokens) is held back for the final fix pass and the
finalize step: ``exhausted(include_reserve=True)`` reports once the remaining
budget has fallen into the reserve, ``exhausted(include_reserve=False)`` only
once the budget is fully spent.  ``unit_allowance`` hands each unit a fair
share of what is left above the reserve.

The budget is a runaway guard, not what bounds a unit (its step cap does):
``scale_to(module_units)`` re-derives the limits from the task size
(``scaled_limits``) once the digest knows it; the defaults below apply only
until then.  A limit set by argument or env is never rescaled.

Environment defaults (a value of "0" or "none" for a maximum means unlimited):
    AGENT_MAX_TOTAL_TOKENS=40000000  AGENT_MAX_SECONDS=14400
    AGENT_RESERVE_SECONDS=1200       AGENT_RESERVE_TOKENS=4000000
"""
from __future__ import annotations

import math
import os
import time
from typing import Any, Callable

DEFAULT_MAX_TOKENS = 40_000_000  # pre-digest defaults (a mid-size task); see scale_to
DEFAULT_MAX_SECONDS = 14_400.0
DEFAULT_RESERVE_SECONDS = 1200.0
DEFAULT_RESERVE_TOKENS = 4_000_000

# scaled_limits: base + per module unit, uncapped (a larger task gets the same rate per unit).
# Sized so that a module unit of the lowest weight (~0.6) still fits its 48-step cap at ~100k
# tokens (a context at main.py's 300k-char threshold) and ~80 s a response (the model call plus
# its tools and in-unit checks).
SCALED_BASE_TOKENS = 10_000_000
SCALED_UNIT_TOKENS = 8_000_000
SCALED_BASE_SECONDS = 7200.0
SCALED_UNIT_SECONDS = 6000.0

SHARE_FACTOR = 1.0          # strict fair share: an early unit never starves the later ones
MIN_UNIT_SECONDS = 300.0    # floor when anything is left, never above a weight-1 share
MIN_UNIT_TOKENS = 300_000
MAX_RESERVE_FRACTION = 0.5  # a reserve never swallows more than half the budget


def _env_value(name: str) -> float | None:
    """A valid env number ("none" reads as 0), else None."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    if raw.lower() == "none":
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _env_number(name: str, default: float) -> float:
    value = _env_value(name)
    return default if value is None else value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _setting(explicit: float | None, env_name: str, default: float) -> float:
    """Explicit argument, else env, else default (an invalid value falls back)."""
    value = _env_number(env_name, default) if explicit is None else _number(explicit)
    return default if value is None else value


def _chosen(explicit: float | None, env_name: str) -> bool:
    """True when a setting came from the caller or a valid env value, not the default."""
    return explicit is not None or _env_value(env_name) is not None


def _limit(explicit: float | None, env_name: str, default: float) -> float | None:
    """Resolve a maximum: explicit argument, else env, else default; 0 means unlimited."""
    value = _setting(explicit, env_name, default)
    return None if value == 0 else value


def _capped(reserve: float, limit: float | None) -> float:
    return reserve if limit is None else min(reserve, limit * MAX_RESERVE_FRACTION)


def _units(value: Any) -> int:
    number = _number(value)
    return max(1, int(number)) if number else 1


def scaled_limits(module_units: int) -> tuple[int, float]:
    """(max tokens, max seconds) for a task of ``module_units`` units (< 1 counts as 1):
    base + per unit."""
    units = _units(module_units)
    return (SCALED_BASE_TOKENS + SCALED_UNIT_TOKENS * units,
            SCALED_BASE_SECONDS + SCALED_UNIT_SECONDS * units)


class RunBudget:
    def __init__(self, *, max_tokens: int | None = None, max_seconds: float | None = None,
                 reserve_seconds: float | None = None, reserve_tokens: int | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.started = float(clock())
        tokens = _limit(max_tokens, "AGENT_MAX_TOTAL_TOKENS", DEFAULT_MAX_TOKENS)
        self.max_tokens: int | None = None if tokens is None else int(tokens)
        self.max_seconds: float | None = _limit(max_seconds, "AGENT_MAX_SECONDS",
                                                DEFAULT_MAX_SECONDS)
        # what scale_to must keep: explicit limits and the uncapped reserves
        self._fixed_tokens = _chosen(max_tokens, "AGENT_MAX_TOTAL_TOKENS")
        self._fixed_seconds = _chosen(max_seconds, "AGENT_MAX_SECONDS")
        self._wanted_reserve_seconds = _setting(reserve_seconds, "AGENT_RESERVE_SECONDS",
                                                DEFAULT_RESERVE_SECONDS)
        self._wanted_reserve_tokens = _setting(reserve_tokens, "AGENT_RESERVE_TOKENS",
                                               DEFAULT_RESERVE_TOKENS)
        self.reserve_seconds, self.reserve_tokens = self._reserves()
        self.scaled_for_units: int | None = None
        self.tokens_used: int = 0
        self.requests: int = 0
        self.estimated_requests: int = 0

    def _reserves(self) -> tuple[float, int]:
        # a reserve never swallows more than MAX_RESERVE_FRACTION of its limit
        return (_capped(self._wanted_reserve_seconds, self.max_seconds),
                int(_capped(self._wanted_reserve_tokens, self.max_tokens)))

    def scale_to(self, module_units: int) -> bool:
        """Re-derive the limits for a task of ``module_units`` units (``scaled_limits``).

        A dimension set by argument or env (unlimited included) keeps its value; the
        reserves are recomputed as in __init__.  Usage and the start time are kept.
        Returns True when a limit or reserve changed; a repeated call is a no-op.
        """
        units = _units(module_units)
        tokens, seconds = scaled_limits(units)
        before = (self.max_tokens, self.max_seconds, self.reserve_seconds, self.reserve_tokens)
        if not self._fixed_tokens:
            self.max_tokens = tokens
        if not self._fixed_seconds:
            self.max_seconds = seconds
        self.reserve_seconds, self.reserve_tokens = self._reserves()
        self.scaled_for_units = units
        return before != (self.max_tokens, self.max_seconds, self.reserve_seconds,
                          self.reserve_tokens)

    # ------------------------------------------------------------------ usage
    def record(self, usage_row: dict | None, estimated_tokens: int) -> int:
        """Add one request's tokens: total_tokens, else input+output, else the estimate."""
        row = usage_row if isinstance(usage_row, dict) else {}
        estimate = _number(estimated_tokens)
        estimate_int = int(estimate) if estimate is not None else 0
        total = _number(row.get("total_tokens"))
        tokens: int
        if total is not None and total > 0:
            tokens = int(total)
        else:
            prompt = _number(row.get("input_tokens"))
            if prompt is None:
                prompt = _number(row.get("prompt_tokens"))
            output = _number(row.get("output_tokens"))
            if output is None:
                output = _number(row.get("completion_tokens"))
            if prompt is not None and output is not None and prompt + output > 0:
                tokens = int(prompt + output)
            elif prompt is not None or output is not None:
                # Partial counters: never count less than what the provider reported.
                tokens = max(int((prompt or 0) + (output or 0)), estimate_int)
                self.estimated_requests += 1
            else:
                tokens = estimate_int
                self.estimated_requests += 1
        self.requests += 1
        self.tokens_used += max(0, tokens)
        return self.tokens_used

    # ------------------------------------------------------------------ state
    def elapsed(self) -> float:
        return max(0.0, float(self.clock()) - self.started)

    @property
    def deadline(self) -> float | None:
        """Monotonic time at which the whole budget ends (None when unlimited)."""
        return None if self.max_seconds is None else self.started + self.max_seconds

    def seconds_left(self) -> float | None:
        if self.max_seconds is None:
            return None
        return max(0.0, self.max_seconds - self.elapsed())

    def tokens_left(self) -> int | None:
        if self.max_tokens is None:
            return None
        return max(0, self.max_tokens - self.tokens_used)

    def exhausted(self, *, include_reserve: bool = True) -> str | None:
        """Reason string when the budget (or, with include_reserve, the reserve) is reached."""
        seconds = self.seconds_left()
        if seconds is not None:
            if seconds <= 0:
                return (f"time budget exhausted: {self.elapsed():.0f}s of "
                        f"{self.max_seconds:.0f}s used")
            if include_reserve and seconds <= self.reserve_seconds:
                return (f"time reserve reached: {seconds:.0f}s left <= reserve "
                        f"{self.reserve_seconds:.0f}s")
        tokens = self.tokens_left()
        if tokens is not None:
            if tokens <= 0:
                return (f"token budget exhausted: {self.tokens_used} of "
                        f"{self.max_tokens} used")
            if include_reserve and tokens <= self.reserve_tokens:
                return (f"token reserve reached: {tokens} left <= reserve "
                        f"{self.reserve_tokens}")
        return None

    # -------------------------------------------------------------- allowance
    @staticmethod
    def _share(left: float, reserve: float, parts: float, weight: float,
               floor: float) -> float:
        if left <= 0:
            return 0.0
        usable = max(0.0, left - reserve)
        share = min(usable / parts * weight * SHARE_FACTOR, usable)
        # the floor never exceeds a weight-1 share: floors taken by early units would starve later ones
        return max(share, min(floor, left, usable / parts))

    def unit_allowance(self, units_left: int, weight: float = 1.0, *,
                       include_reserve: bool = True,
                       weight_left: float | None = None) -> tuple[float | None, int | None]:
        """(monotonic deadline, token cap) for the next unit.

        Fair share of (left - reserve) / units_left * weight * SHARE_FACTOR, never beyond the
        reserve boundary, with a floor of MIN_UNIT_SECONDS / MIN_UNIT_TOKENS (never above
        what is left, nor above the share of a weight-1 unit).  ``weight_left`` > 0 (the
        summed weight of this and every later unit) replaces units_left as the divisor, so
        units that each spend their share split what is left in proportion to their
        weights.  ``include_reserve=False`` treats the reserve as spendable (for the final
        fix pass).  Components are None when that dimension is unlimited.
        """
        total = _number(weight_left)
        parts = total if total else float(max(1, int(units_left or 1)))
        factor = float(weight) if _number(weight) else 1.0
        now = float(self.clock())
        deadline: float | None = None
        seconds = self.seconds_left()
        if seconds is not None:
            reserve = self.reserve_seconds if include_reserve else 0.0
            deadline = now + self._share(seconds, reserve, parts, factor, MIN_UNIT_SECONDS)
        cap: int | None = None
        tokens = self.tokens_left()
        if tokens is not None:
            reserve_t = float(self.reserve_tokens) if include_reserve else 0.0
            cap = int(self._share(float(tokens), reserve_t, parts, factor,
                                  float(MIN_UNIT_TOKENS)))
        return deadline, cap

    def summary(self) -> dict[str, Any]:
        seconds = self.seconds_left()
        return {
            "tokens_used": self.tokens_used,
            "max_tokens": self.max_tokens,
            "tokens_left": self.tokens_left(),
            "reserve_tokens": self.reserve_tokens,
            "elapsed_seconds": round(self.elapsed(), 2),
            "max_seconds": self.max_seconds,
            "seconds_left": None if seconds is None else round(seconds, 2),
            "reserve_seconds": self.reserve_seconds,
            "requests": self.requests,
            "estimated_requests": self.estimated_requests,
            "exhausted": self.exhausted(include_reserve=False),
            "in_reserve": self.exhausted(include_reserve=True),
            "scaled_for_units": self.scaled_for_units,
        }
