from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from smdfjsp.core.types import DecodeContext, EncodedIndividual, RollingState, ScheduleRecord, SMDFJSPInstance
from smdfjsp.eda_ts import EDATS, EDATSConfig
from smdfjsp.model.evaluator import evaluate_individual
from smdfjsp.rolling.controller import build_remaining_subproblem, lift_records_from_subproblem


SelectionStrategy = Literal["cost_then_makespan", "min_makespan", "knee", "random"]


@dataclass
class SubproblemCandidate:
    solution: EncodedIndividual
    sub_records: List[ScheduleRecord]
    lifted_records: List[ScheduleRecord]


@dataclass
class SubproblemSolveResult:
    nd_solutions: List[EncodedIndividual]
    candidates: List[SubproblemCandidate]
    selected: Optional[SubproblemCandidate]
    selected_index: int
    runtime_s: float
    selection_strategy: SelectionStrategy
    selection_cycle: int
    round_index: int
    subproblem_name: str


def build_subproblem_decode_context(sub_instance: SMDFJSPInstance, state: RollingState) -> DecodeContext:
    eligible = {j.job_id for j in sub_instance.jobs}
    sub_job_ready = {j.job_id: float(state.job_ready.get(j.job_id, 0.0)) for j in sub_instance.jobs}
    return DecodeContext(
        current_time=float(state.current_time),
        eligible_job_ids=eligible,
        completed_ops_by_job={j.job_id: 0 for j in sub_instance.jobs},
        in_progress_ops={},
        frozen_job_ready=sub_job_ready,
        frozen_machine_ready=dict(state.machine_ready),
        frozen_records=[],
        frozen_ua_by_job={},
        include_transport_for_incomplete_jobs=False,
    )


def _sort_indices_by_objective(candidates: List[SubproblemCandidate], key_fn) -> List[int]:
    pairs = sorted(
        enumerate(candidates),
        key=lambda x: key_fn(x[1].solution.objectives if x[1].solution.objectives is not None else (float("inf"), float("inf"))),
    )
    return [x[0] for x in pairs]


def _select_candidate_index(
    candidates: List[SubproblemCandidate],
    strategy: SelectionStrategy,
    selection_cycle: int,
    round_index: int,
    rng: random.Random,
) -> int:
    if not candidates:
        return -1
    cycle = max(1, int(selection_cycle))

    if strategy == "random":
        return int(rng.randrange(len(candidates)))

    if strategy == "cost_then_makespan":
        order = _sort_indices_by_objective(candidates, key_fn=lambda o: (o[0], o[1]))
    elif strategy == "min_makespan":
        order = _sort_indices_by_objective(candidates, key_fn=lambda o: (o[1], o[0]))
    elif strategy == "knee":
        objs = [x.solution.objectives for x in candidates if x.solution.objectives is not None]
        if not objs:
            return 0
        costs = [o[0] for o in objs]
        mks = [o[1] for o in objs]
        c_min, c_max = min(costs), max(costs)
        m_min, m_max = min(mks), max(mks)

        def knee_score(obj):
            cost, mk = obj
            nc = 0.0 if c_max == c_min else (cost - c_min) / (c_max - c_min)
            nm = 0.0 if m_max == m_min else (mk - m_min) / (m_max - m_min)
            return math.sqrt(nc * nc + nm * nm)

        order = _sort_indices_by_objective(candidates, key_fn=lambda o: (knee_score(o), o[0], o[1]))
    else:
        raise ValueError(f"Unknown selection strategy: {strategy}")

    rank = int(round_index) % cycle
    rank = min(rank, len(order) - 1)
    return order[rank]


def solve_rescheduling_subproblem_with_edats(
    instance: SMDFJSPInstance,
    state: RollingState,
    config: EDATSConfig,
    selection_strategy: SelectionStrategy = "cost_then_makespan",
    selection_cycle: int = 1,
    round_index: int = 0,
    seed: Optional[int] = None,
) -> SubproblemSolveResult:
    start = time.perf_counter()
    sub = build_remaining_subproblem(instance, state)
    if not sub.instance.jobs:
        return SubproblemSolveResult(
            nd_solutions=[],
            candidates=[],
            selected=None,
            selected_index=-1,
            runtime_s=time.perf_counter() - start,
            selection_strategy=selection_strategy,
            selection_cycle=max(1, int(selection_cycle)),
            round_index=int(round_index),
            subproblem_name=sub.instance.name,
        )

    solve_seed = int(seed if seed is not None else config.seed)
    cfg = EDATSConfig(
        popsize=config.popsize,
        max_iter=config.max_iter,
        time_limit_s=config.time_limit_s,
        alpha=config.alpha,
        beta=config.beta,
        gamma=config.gamma,
        mu=config.mu,
        epsilon=config.epsilon,
        tmax=config.tmax,
        nd_pool_max=config.nd_pool_max,
        seed=solve_seed,
        use_multi_population=config.use_multi_population,
        use_nd_memory=config.use_nd_memory,
        use_ts=config.use_ts,
    )
    decode_ctx = build_subproblem_decode_context(sub.instance, state)
    run_result = EDATS(sub.instance, cfg).run(eval_ctx=decode_ctx)
    nd = [x for x in run_result.nd_solutions if x.objectives is not None]

    candidates: List[SubproblemCandidate] = []
    for sol in nd:
        ev = evaluate_individual(sub.instance, sol, ctx=decode_ctx)
        if not ev.feasible:
            continue
        lifted = lift_records_from_subproblem(ev.records, sub.op_offset_by_job)
        candidates.append(SubproblemCandidate(solution=sol, sub_records=ev.records, lifted_records=lifted))

    selector_rng = random.Random(solve_seed + 100003 * (int(round_index) + 1))
    selected_idx = _select_candidate_index(
        candidates=candidates,
        strategy=selection_strategy,
        selection_cycle=selection_cycle,
        round_index=round_index,
        rng=selector_rng,
    )
    selected = candidates[selected_idx] if selected_idx >= 0 else None
    return SubproblemSolveResult(
        nd_solutions=nd,
        candidates=candidates,
        selected=selected,
        selected_index=selected_idx,
        runtime_s=time.perf_counter() - start,
        selection_strategy=selection_strategy,
        selection_cycle=max(1, int(selection_cycle)),
        round_index=int(round_index),
        subproblem_name=sub.instance.name,
    )

