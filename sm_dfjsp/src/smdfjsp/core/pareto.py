from __future__ import annotations

# Pareto utilities shared by EDA-TS and baselines.
# All objectives are minimization objectives.

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

from smdfjsp.core.types import ObjPair


def dominates(a: ObjPair, b: ObjPair) -> bool:
    """Return True if a Pareto-dominates b for minimization."""
    # a dominates b if:
    # - a is no worse on every objective
    # - and strictly better on at least one objective
    return (a[0] <= b[0] and a[1] <= b[1]) and (a[0] < b[0] or a[1] < b[1])


def fast_non_dominated_sort(objs: Sequence[ObjPair]) -> List[List[int]]:
    """NSGA-II style non-dominated sorting."""
    n = len(objs)
    if n == 0:
        return []
    # dominates_set[p] = list of indices dominated by p
    dominates_set: List[List[int]] = [[] for _ in range(n)]
    # dominated_count[p] = number of solutions that dominate p
    dominated_count = [0] * n
    # fronts[0] will be the first non-dominated front
    fronts: List[List[int]] = [[]]
    for p in range(n):
        for q in range(n):
            if p == q:
                continue
            if dominates(objs[p], objs[q]):
                dominates_set[p].append(q)
            elif dominates(objs[q], objs[p]):
                dominated_count[p] += 1
        if dominated_count[p] == 0:
            fronts[0].append(p)
    i = 0
    while i < len(fronts) and fronts[i]:
        next_front: List[int] = []
        for p in fronts[i]:
            for q in dominates_set[p]:
                dominated_count[q] -= 1
                if dominated_count[q] == 0:
                    next_front.append(q)
        if next_front:
            fronts.append(next_front)
        i += 1
    return fronts


def crowding_distance(objs: Sequence[ObjPair], front: Sequence[int]) -> List[float]:
    """Crowding distance for one front."""
    if not front:
        return []
    if len(front) <= 2:
        return [float("inf")] * len(front)
    # Larger distance means less crowded (preferred for diversity).
    distance = [0.0] * len(front)
    index_pos = {idx: pos for pos, idx in enumerate(front)}
    for dim in (0, 1):
        ordered = sorted(front, key=lambda idx: objs[idx][dim])
        # Boundary points get infinite distance.
        distance[index_pos[ordered[0]]] = float("inf")
        distance[index_pos[ordered[-1]]] = float("inf")
        min_v = objs[ordered[0]][dim]
        max_v = objs[ordered[-1]][dim]
        if max_v == min_v:
            continue
        for i in range(1, len(ordered) - 1):
            prev_v = objs[ordered[i - 1]][dim]
            next_v = objs[ordered[i + 1]][dim]
            distance[index_pos[ordered[i]]] += (next_v - prev_v) / (max_v - min_v)
    return distance


def get_non_dominated_indices(objs: Sequence[ObjPair]) -> List[int]:
    # Convenience helper: return first front only.
    fronts = fast_non_dominated_sort(objs)
    return fronts[0] if fronts else []


def merge_non_dominated(
    base: Iterable[Tuple[ObjPair, object]],
    incoming: Iterable[Tuple[ObjPair, object]],
    max_size: int | None = None,
) -> List[Tuple[ObjPair, object]]:
    """Merge two pools and keep only non-dominated entries."""
    # Merge old and incoming pools first.
    merged = list(base) + list(incoming)
    if not merged:
        return []
    objs = [item[0] for item in merged]
    nd = get_non_dominated_indices(objs)
    result = [merged[i] for i in nd]
    if max_size is not None and len(result) > max_size:
        # Keep smallest cost first when truncation is needed.
        result = sorted(result, key=lambda x: (x[0][0], x[0][1]))[:max_size]
    return result

