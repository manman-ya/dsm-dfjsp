from __future__ import annotations

# NSGA-II baseline for SM-DFJSP:
# - standard tournament selection
# - crossover/mutation variation
# - NSGA-II environmental selection (rank + crowding)

import time
from dataclasses import dataclass
from typing import Dict, List, Tuple

from smdfjsp.baselines.common import evaluate_population, nsga2_select
from smdfjsp.baselines.variation import crossover, mutate
from smdfjsp.core.encoding import build_option_index, build_random_individual
from smdfjsp.core.pareto import crowding_distance, fast_non_dominated_sort, merge_non_dominated
from smdfjsp.core.random_utils import make_rng
from smdfjsp.core.types import EncodedIndividual, SMDFJSPInstance
from smdfjsp.eda_ts.algorithm import RunResult


@dataclass
class NSGAIIConfig:
    # Population size.
    popsize: int = 50
    # Max generation count.
    max_iter: int = 100
    # Run time limit in seconds.
    time_limit_s: float = 100.0
    # Crossover probability.
    cr: float = 0.7
    # Mutation probability.
    mr: float = 0.3
    # Random seed.
    seed: int = 42
    # Max ND solutions to return.
    nd_pool_max: int = 300


def _rank_and_crowding(pop: List[EncodedIndividual]) -> Tuple[Dict[int, int], Dict[int, float]]:
    # Compute NSGA-II rank/crowding maps for the current population.
    objs = [ind.objectives for ind in pop]  # type: ignore[list-item]
    fronts = fast_non_dominated_sort(objs)  # type: ignore[arg-type]
    rank: Dict[int, int] = {}
    crowd: Dict[int, float] = {}
    for fi, front in enumerate(fronts):
        d = crowding_distance(objs, front)  # type: ignore[arg-type]
        for idx, c in zip(front, d):
            rank[idx] = fi
            crowd[idx] = c
    return rank, crowd


def _tournament(pop: List[EncodedIndividual], rank: Dict[int, int], crowd: Dict[int, float], rng) -> EncodedIndividual:
    # Binary tournament:
    # 1) lower rank wins
    # 2) if tie, larger crowding wins
    # 3) if still tie, random pick
    i, j = rng.py_rng.sample(range(len(pop)), 2)
    if rank[i] < rank[j]:
        return pop[i]
    if rank[j] < rank[i]:
        return pop[j]
    if crowd[i] > crowd[j]:
        return pop[i]
    if crowd[j] > crowd[i]:
        return pop[j]
    return pop[i] if rng.py_rng.random() < 0.5 else pop[j]


def run_nsgaii(instance: SMDFJSPInstance, cfg: NSGAIIConfig) -> RunResult:
    # Initialize random population.
    rng = make_rng(cfg.seed)
    option_index = build_option_index(instance)
    pop = [build_random_individual(instance, option_index, rng) for _ in range(cfg.popsize)]
    evaluate_population(instance, pop)
    history: List[Dict[str, float]] = []
    start = time.time()

    for it in range(1, cfg.max_iter + 1):
        # Time stop condition.
        if (time.time() - start) >= cfg.time_limit_s:
            break
        # Parent selection helpers.
        rank, crowd = _rank_and_crowding(pop)
        offspring: List[EncodedIndividual] = []
        # Build offspring population.
        while len(offspring) < cfg.popsize:
            p1 = _tournament(pop, rank, crowd, rng)
            p2 = _tournament(pop, rank, crowd, rng)
            if rng.py_rng.random() < cfg.cr:
                # Variation via crossover + mutation.
                c1 = crossover(p1, p2, instance, option_index, rng)
            else:
                # Or mutation-only branch.
                c1 = mutate(p1, instance, option_index, rng, cfg.mr)
            c1 = mutate(c1, instance, option_index, rng, cfg.mr)
            offspring.append(c1)
        # Evaluate children and keep next generation with NSGA-II selection.
        evaluate_population(instance, offspring)
        pop = nsga2_select(pop + offspring, cfg.popsize)
        # Store simple monitoring stats.
        objs = [x.objectives for x in pop if x.objectives is not None]
        history.append({"iter": it, "best_cost": min(o[0] for o in objs), "best_makespan": min(o[1] for o in objs)})

    # Final ND front extraction.
    nd = merge_non_dominated(
        [],
        [(ind.objectives, ind) for ind in pop if ind.objectives is not None],
        max_size=cfg.nd_pool_max,
    )
    return RunResult(nd_solutions=[x[1] for x in nd], history=history)

