from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

import numpy as np

from smdfjsp.core.pareto import dominates, get_non_dominated_indices
from smdfjsp.core.types import ObjPair


def euclidean(a: ObjPair, b: ObjPair) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def build_pf_known(fronts: Sequence[Sequence[ObjPair]]) -> List[ObjPair]:
    union = [x for f in fronts for x in f]
    if not union:
        return []
    nd_idx = get_non_dominated_indices(union)
    return [union[i] for i in nd_idx]


def gd(pf_a: Sequence[ObjPair], pf_true: Sequence[ObjPair]) -> float:
    if not pf_a or not pf_true:
        return float("inf")
    d2 = []
    for a in pf_a:
        near = min(euclidean(a, t) for t in pf_true)
        d2.append(near**2)
    return float(math.sqrt(sum(d2)) / len(d2))


def igd(pf_a: Sequence[ObjPair], pf_true: Sequence[ObjPair]) -> float:
    if not pf_a or not pf_true:
        return float("inf")
    ds = []
    for t in pf_true:
        near = min(euclidean(t, a) for a in pf_a)
        ds.append(near)
    return float(sum(ds) / len(ds))


def c_metric(a: Sequence[ObjPair], b: Sequence[ObjPair]) -> float:
    if not b:
        return 0.0
    dominated = 0
    for bb in b:
        if any(dominates(aa, bb) for aa in a):
            dominated += 1
    return dominated / len(b)


def ods(front: Sequence[ObjPair]) -> float:
    """Objective deviation sum used in parameter design."""
    if not front:
        return float("inf")
    arr = np.array(front, dtype=float)
    mins = arr.min(axis=0)
    mins[mins == 0] = 1.0
    score = ((arr - mins) / mins).sum(axis=1).mean()
    return float(score)

