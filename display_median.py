"""Time-windowed median aggregation for displayed tracking positions."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping


class DisplayMedianBuffer:
    """Collect positions and return one coordinate-wise median per window."""

    def __init__(self) -> None:
        self._samples: list[dict[str, float]] = []
        self._axes: tuple[str, ...] | None = None

    def add(self, position: Mapping[str, float]) -> None:
        sample = {axis: float(value) for axis, value in position.items()}
        if not sample:
            raise ValueError("position must contain at least one coordinate")
        if not all(math.isfinite(value) for value in sample.values()):
            raise ValueError("position coordinates must be finite")

        axes = tuple(sample)
        if self._axes is None:
            self._axes = axes
        elif set(axes) != set(self._axes):
            raise ValueError("position coordinates must remain consistent")

        self._samples.append(sample)

    def take_median(self) -> dict[str, float] | None:
        """Return and remove the samples collected since the previous call."""
        if not self._samples:
            return None

        samples = self._samples
        self._samples = []
        return {
            axis: statistics.median(sample[axis] for sample in samples)
            for axis in self._axes
        }

    def clear(self) -> None:
        self._samples = []
        self._axes = None

    def __len__(self) -> int:
        return len(self._samples)
