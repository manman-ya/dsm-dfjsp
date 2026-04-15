from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, List, Sequence, Tuple


def _rank_abs_values(values: Sequence[float]) -> List[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[order[k]] = avg_rank
        i = j
    return ranks


def wilcoxon_signed_rank(
    a: Sequence[float],
    b: Sequence[float],
    alpha: float = 0.05,
    smaller_is_better: bool = True,
) -> Tuple[float, float, str]:
    """
    Return (Wm, p_value, win) with two-sided normal approximation.
    win in {"+", "-", "="} from perspective of sample a.
    """
    if len(a) != len(b):
        raise ValueError("Samples must have the same length.")
    diffs = [x - y for x, y in zip(a, b) if (x - y) != 0.0]
    n = len(diffs)
    if n == 0:
        return 0.0, 1.0, "="

    abs_vals = [abs(x) for x in diffs]
    ranks = _rank_abs_values(abs_vals)
    w_pos = sum(r for r, d in zip(ranks, diffs) if d > 0)
    w_neg = sum(r for r, d in zip(ranks, diffs) if d < 0)
    w_m = min(w_pos, w_neg)

    # Tie-corrected variance for approximate z-test.
    tie_counts = Counter(abs_vals)
    tie_corr = sum(t * (t + 1) * (2 * t + 1) for t in tie_counts.values() if t > 1)
    mu = n * (n + 1) / 4.0
    var = (n * (n + 1) * (2 * n + 1) - tie_corr) / 24.0
    if var <= 0:
        p_value = 1.0
    else:
        z = (abs(w_m - mu) - 0.5) / math.sqrt(var)
        # 2 * (1 - Phi(|z|))
        p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))
        p_value = max(0.0, min(1.0, p_value))

    if p_value >= alpha:
        return float(w_m), float(p_value), "="

    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    if smaller_is_better:
        win = "+" if mean_a < mean_b else "-"
    else:
        win = "+" if mean_a > mean_b else "-"
    return float(w_m), float(p_value), win

