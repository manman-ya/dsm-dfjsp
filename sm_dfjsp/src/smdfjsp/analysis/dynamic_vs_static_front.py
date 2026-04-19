from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from smdfjsp.core.pareto import dominates, get_non_dominated_indices
from smdfjsp.core.types import EncodedIndividual, Job, ObjPair, SMDFJSPInstance
from smdfjsp.eda_ts import EDATS, EDATSConfig


@dataclass(frozen=True)
class StaticReferenceFrontResult:
    instance: SMDFJSPInstance
    runtime_s: float
    front_points: List[ObjPair]
    front_solutions: List[EncodedIndividual]


def clone_instance_all_known(instance: SMDFJSPInstance, release_time_value: float = 0.0) -> SMDFJSPInstance:
    jobs: List[Job] = [
        Job(
            job_id=j.job_id,
            type_id=j.type_id,
            operations=list(j.operations),
            release_time=float(release_time_value),
        )
        for j in instance.jobs
    ]
    return SMDFJSPInstance(
        name=f"{instance.name}_all_known_t0",
        num_types=instance.num_types,
        jobs=jobs,
        srus=list(instance.srus),
        transport_time=dict(instance.transport_time),
        transport_cost_per_time=dict(instance.transport_cost_per_time),
        metadata={**instance.metadata, "static_full_information_oracle": True},
        initial_jobs=[j.job_id for j in jobs],
        arrival_stream=[],
    )


def _stable_unique_point_pairs(points: Iterable[Tuple[ObjPair, EncodedIndividual]]) -> List[Tuple[ObjPair, EncodedIndividual]]:
    out: List[Tuple[ObjPair, EncodedIndividual]] = []
    seen = set()
    for obj, sol in points:
        key = (float(obj[0]), float(obj[1]))
        if key in seen:
            continue
        seen.add(key)
        out.append((key, sol))
    return out


def compute_static_reference_front(
    instance: SMDFJSPInstance,
    config: EDATSConfig,
    seed: int,
) -> StaticReferenceFrontResult:
    oracle_instance = clone_instance_all_known(instance, release_time_value=0.0)
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
        seed=int(seed),
        use_multi_population=config.use_multi_population,
        use_nd_memory=config.use_nd_memory,
        use_ts=config.use_ts,
    )
    t0 = time.perf_counter()
    run = EDATS(oracle_instance, cfg).run()
    runtime_s = time.perf_counter() - t0

    candidates: List[Tuple[ObjPair, EncodedIndividual]] = []
    for sol in run.nd_solutions:
        if sol.objectives is None:
            continue
        if not math.isfinite(sol.objectives[0]) or not math.isfinite(sol.objectives[1]):
            continue
        candidates.append(((float(sol.objectives[0]), float(sol.objectives[1])), sol))
    candidates = _stable_unique_point_pairs(candidates)
    if not candidates:
        return StaticReferenceFrontResult(
            instance=oracle_instance,
            runtime_s=runtime_s,
            front_points=[],
            front_solutions=[],
        )

    objs = [x[0] for x in candidates]
    nd_idx = get_non_dominated_indices(objs)
    nd_pairs = [candidates[i] for i in nd_idx]
    nd_pairs = sorted(nd_pairs, key=lambda x: (x[0][0], x[0][1]))
    return StaticReferenceFrontResult(
        instance=oracle_instance,
        runtime_s=runtime_s,
        front_points=[x[0] for x in nd_pairs],
        front_solutions=[x[1] for x in nd_pairs],
    )


def extract_static_representative_points(front: List[ObjPair]) -> Dict[str, int]:
    if not front:
        return {}
    min_cost_idx = min(range(len(front)), key=lambda i: (front[i][0], front[i][1]))
    min_mk_idx = min(range(len(front)), key=lambda i: (front[i][1], front[i][0]))

    costs = [x[0] for x in front]
    makespans = [x[1] for x in front]
    c_min, c_max = min(costs), max(costs)
    m_min, m_max = min(makespans), max(makespans)

    def knee_score(obj: ObjPair) -> float:
        c, m = obj
        nc = 0.0 if c_max == c_min else (c - c_min) / (c_max - c_min)
        nm = 0.0 if m_max == m_min else (m - m_min) / (m_max - m_min)
        return math.sqrt(nc * nc + nm * nm)

    knee_idx = min(range(len(front)), key=lambda i: (knee_score(front[i]), front[i][0], front[i][1]))
    return {
        "min_cost": int(min_cost_idx),
        "min_makespan": int(min_mk_idx),
        "knee": int(knee_idx),
    }


def map_dynamic_point_to_static_front(
    dynamic_point: ObjPair,
    static_front: List[ObjPair],
) -> Dict[str, object]:
    if not static_front:
        return {
            "dominated_by_static_front": False,
            "nearest_front_cost": float("inf"),
            "nearest_front_makespan": float("inf"),
            "distance_to_static_front": float("inf"),
            "cost_gap_to_front": float("inf"),
            "makespan_gap_to_front": float("inf"),
            "nearest_front_index": -1,
        }

    # Normalize before distance to avoid scale distortion between cost and makespan.
    costs = [x[0] for x in static_front] + [float(dynamic_point[0])]
    makespans = [x[1] for x in static_front] + [float(dynamic_point[1])]
    c_min, c_max = min(costs), max(costs)
    m_min, m_max = min(makespans), max(makespans)

    def norm(obj: ObjPair) -> Tuple[float, float]:
        c, m = float(obj[0]), float(obj[1])
        nc = 0.0 if c_max == c_min else (c - c_min) / (c_max - c_min)
        nm = 0.0 if m_max == m_min else (m - m_min) / (m_max - m_min)
        return nc, nm

    dyn_n = norm(dynamic_point)
    nearest_idx = -1
    nearest_dist = float("inf")
    for i, p in enumerate(static_front):
        p_n = norm(p)
        d = math.sqrt((dyn_n[0] - p_n[0]) ** 2 + (dyn_n[1] - p_n[1]) ** 2)
        if d < nearest_dist:
            nearest_dist = d
            nearest_idx = i
    nearest = static_front[nearest_idx]
    dominated = any(dominates(p, dynamic_point) for p in static_front)
    return {
        "dominated_by_static_front": bool(dominated),
        "nearest_front_cost": float(nearest[0]),
        "nearest_front_makespan": float(nearest[1]),
        "distance_to_static_front": float(nearest_dist),
        "cost_gap_to_front": float((dynamic_point[0] - nearest[0]) / max(1e-9, nearest[0])),
        "makespan_gap_to_front": float((dynamic_point[1] - nearest[1]) / max(1e-9, nearest[1])),
        "nearest_front_index": int(nearest_idx),
    }


def summarize_dynamic_vs_static_results(
    rows: List[Dict[str, object]],
    group_keys: Tuple[str, ...] = ("instance", "method", "selection_policy"),
) -> List[Dict[str, object]]:
    numeric_cols = [
        "total_cost",
        "makespan",
        "distance_to_static_front",
        "cost_gap_to_front",
        "makespan_gap_to_front",
        "avg_response_time",
        "avg_flow_time",
        "reschedule_count",
        "runtime",
    ]
    grouped: Dict[Tuple[object, ...], List[Dict[str, object]]] = {}
    for row in rows:
        key = tuple(row.get(k) for k in group_keys)
        grouped.setdefault(key, []).append(row)

    out: List[Dict[str, object]] = []
    for key, items in sorted(grouped.items(), key=lambda x: tuple(str(v) for v in x[0])):
        summary: Dict[str, object] = {}
        for i, k in enumerate(group_keys):
            summary[k] = key[i]
        summary["n_runs"] = len(items)
        for col in numeric_cols:
            vals = [float(x[col]) for x in items if col in x and math.isfinite(float(x[col]))]
            if not vals:
                summary[f"mean_{col}"] = float("inf")
                summary[f"std_{col}"] = float("inf")
                continue
            summary[f"mean_{col}"] = float(sum(vals) / len(vals))
            if len(vals) > 1:
                mean = sum(vals) / len(vals)
                var = sum((x - mean) ** 2 for x in vals) / len(vals)
                summary[f"std_{col}"] = float(math.sqrt(var))
            else:
                summary[f"std_{col}"] = 0.0
        dominated = [1.0 if bool(x.get("dominated_by_static_front", False)) else 0.0 for x in items]
        summary["dominated_ratio"] = float(sum(dominated) / len(dominated))
        out.append(summary)
    return out

