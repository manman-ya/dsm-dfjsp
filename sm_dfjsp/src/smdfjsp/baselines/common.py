from __future__ import annotations

# Shared baseline helpers:
# - evaluate an entire population
# - select next generation with NSGA-II environmental selection

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from smdfjsp.core.pareto import crowding_distance, fast_non_dominated_sort
from smdfjsp.core.types import EncodedIndividual, ObjPair, SMDFJSPInstance
from smdfjsp.model.evaluator import evaluate_individual


def evaluate_population(instance: SMDFJSPInstance, pop: List[EncodedIndividual]) -> None:
    # Fill objective/feasibility for each individual in-place.
    for ind in pop:
        r = evaluate_individual(instance, ind)
        ind.objectives = r.objectives
        ind.feasible = r.feasible


def nsga2_select(pop: List[EncodedIndividual], popsize: int) -> List[EncodedIndividual]:
    # Standard NSGA-II truncation:
    # 1) add complete fronts by rank
    # 2) if one front overflows, keep largest crowding distances
    objs = [ind.objectives for ind in pop]  # type: ignore[list-item]
    fronts = fast_non_dominated_sort(objs)  # type: ignore[arg-type]
    selected: List[EncodedIndividual] = []
    for front in fronts:
        if len(selected) + len(front) <= popsize:
            selected.extend(pop[i] for i in front)
        else:
            dist = crowding_distance(objs, front)  # type: ignore[arg-type]
            pairs = sorted(zip(front, dist), key=lambda x: x[1], reverse=True)
            selected.extend(pop[i] for i, _ in pairs[: popsize - len(selected)])
            break
    return selected

