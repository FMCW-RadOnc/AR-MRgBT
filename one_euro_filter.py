"""Adaptive low-pass filtering for three-dimensional tracking positions.

This is a vector-aware implementation of the One Euro filter described by
Casiez, Roussel, and Vogel. Each coordinate is low-pass filtered separately,
but a shared three-dimensional speed controls the cutoff frequency. Using one
cutoff for all axes avoids distorting the direction of diagonal movement.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping


class OneEuroFilter:
    """Filter a mapping of named coordinates using a shared adaptive cutoff."""

    def __init__(
        self,
        min_cutoff_hz: float,
        beta: float,
        derivative_cutoff_hz: float,
        max_speed_mm_s: float | None = None,
    ):
        if min_cutoff_hz <= 0:
            raise ValueError("min_cutoff_hz must be greater than zero")
        if beta < 0:
            raise ValueError("beta must be zero or greater")
        if derivative_cutoff_hz <= 0:
            raise ValueError("derivative_cutoff_hz must be greater than zero")
        if max_speed_mm_s is not None and max_speed_mm_s <= 0:
            raise ValueError("max_speed_mm_s must be greater than zero when provided")

        self.min_cutoff_hz = float(min_cutoff_hz)
        self.beta = float(beta)
        self.derivative_cutoff_hz = float(derivative_cutoff_hz)
        self.max_speed_mm_s = (
            None if max_speed_mm_s is None else float(max_speed_mm_s)
        )

        self._previous_time = None
        self._previous_raw = None
        self._previous_filtered = None
        self._previous_derivative = None

    @staticmethod
    def _alpha(elapsed_seconds: float, cutoff_hz: float) -> float:
        time_constant = 1.0 / (2.0 * math.pi * cutoff_hz)
        return elapsed_seconds / (elapsed_seconds + time_constant)

    @staticmethod
    def _low_pass(value: float, previous: float, alpha: float) -> float:
        return alpha * value + (1.0 - alpha) * previous

    def reset(self) -> None:
        """Discard all prior measurements."""
        self._previous_time = None
        self._previous_raw = None
        self._previous_filtered = None
        self._previous_derivative = None

    def update(
        self,
        measurement: Mapping[str, float],
        timestamp: float | None = None,
    ) -> dict[str, float]:
        """Return the filtered coordinates for one measurement.

        ``timestamp`` must be monotonic seconds. It is optional in production
        and exposed primarily to make recorded-data playback and tests
        deterministic.
        """
        current = {axis: float(value) for axis, value in measurement.items()}
        if not current:
            raise ValueError("measurement must contain at least one coordinate")
        if not all(math.isfinite(value) for value in current.values()):
            raise ValueError("measurement coordinates must be finite")

        now = time.perf_counter() if timestamp is None else float(timestamp)
        if not math.isfinite(now):
            raise ValueError("timestamp must be finite")

        if self._previous_raw is None:
            self._previous_time = now
            self._previous_raw = current.copy()
            self._previous_filtered = current.copy()
            self._previous_derivative = {axis: 0.0 for axis in current}
            return current.copy()

        if current.keys() != self._previous_raw.keys():
            raise ValueError("measurement coordinates must remain consistent")

        elapsed = now - self._previous_time
        if elapsed <= 0:
            return self._previous_filtered.copy()

        raw_displacement = math.sqrt(
            sum(
                (value - self._previous_raw[axis]) ** 2
                for axis, value in current.items()
            )
        )
        if (
            self.max_speed_mm_s is not None
            and raw_displacement / elapsed > self.max_speed_mm_s
        ):
            # Keep the old timestamp as well as the old position. A sustained
            # real movement will become acceptable after enough physical travel
            # time, while an isolated spike disappears on the next sample.
            return self._previous_filtered.copy()

        derivative_alpha = self._alpha(elapsed, self.derivative_cutoff_hz)
        filtered_derivative = {}
        for axis, value in current.items():
            raw_derivative = (value - self._previous_raw[axis]) / elapsed
            filtered_derivative[axis] = self._low_pass(
                raw_derivative,
                self._previous_derivative[axis],
                derivative_alpha,
            )

        speed = math.sqrt(sum(value * value for value in filtered_derivative.values()))
        cutoff_hz = self.min_cutoff_hz + self.beta * speed
        position_alpha = self._alpha(elapsed, cutoff_hz)
        filtered = {
            axis: self._low_pass(
                value,
                self._previous_filtered[axis],
                position_alpha,
            )
            for axis, value in current.items()
        }

        self._previous_time = now
        self._previous_raw = current
        self._previous_filtered = filtered
        self._previous_derivative = filtered_derivative
        return filtered.copy()
