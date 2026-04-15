from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class RNGPack:
    """Centralized random sources for reproducibility."""

    seed: int
    py_rng: random.Random
    np_rng: np.random.Generator


def make_rng(seed: Optional[int]) -> RNGPack:
    real_seed = 0 if seed is None else int(seed)
    return RNGPack(
        seed=real_seed,
        py_rng=random.Random(real_seed),
        np_rng=np.random.default_rng(real_seed),
    )

