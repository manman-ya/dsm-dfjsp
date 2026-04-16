from __future__ import annotations

import csv
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import yaml

from smdfjsp.core.random_utils import make_rng
from smdfjsp.core.types import Job, Operation, ProcessOption, SMDFJSPInstance, SRU
from smdfjsp.data.io import build_arrival_stream_from_release_time, save_instance_json
from smdfjsp.data.mk_parser import MKInstance, parse_mk_file


@dataclass
class DatasetSpec:
    seed: int
    num_types: int
    total_sru_candidates: List[int]
    total_sru_method: str
    sru_split_method: str
    process_cost_range: Tuple[int, int]
    transport_time_range: Tuple[int, int]
    transport_cost_range: Tuple[int, int]
    process_time_factor_range: Tuple[float, float]
    sru_machine_ratio_range: Tuple[float, float]
    type_assignment: str


def load_dataset_spec(path: str | Path) -> DatasetSpec:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    total_sru_cfg = cfg.get("total_sru", {})
    spec = DatasetSpec(
        seed=int(cfg["seed"]),
        num_types=int(cfg["num_types"]),
        total_sru_candidates=[int(x) for x in total_sru_cfg["candidates"]],
        total_sru_method=str(total_sru_cfg.get("method", "cycle_by_instance")),
        sru_split_method=str(total_sru_cfg.get("split_method", "balanced_min1_randomized")),
        process_cost_range=tuple(cfg["process_cost_range"]),
        transport_time_range=tuple(cfg["transport_time_range"]),
        transport_cost_range=tuple(cfg["transport_cost_range"]),
        process_time_factor_range=tuple(cfg["process_time_factor_range"]),
        sru_machine_ratio_range=tuple(cfg.get("sru_machine_ratio_range", [0.6, 0.9])),
        type_assignment=str(cfg["type_assignment"]["method"]),
    )
    if spec.num_types <= 0:
        raise ValueError("num_types must be >= 1")
    if not spec.total_sru_candidates:
        raise ValueError("total_sru.candidates must not be empty")
    if any(x < spec.num_types for x in spec.total_sru_candidates):
        raise ValueError("each total SRU candidate must be >= num_types to keep each type feasible")
    return spec


def _choose_total_sru(candidates: List[int], seed: int, seed_offset: int, method: str) -> int:
    if method == "cycle_by_instance":
        sorted_candidates = sorted(candidates)
        return int(sorted_candidates[seed_offset % len(sorted_candidates)])
    if method == "random_choice":
        rng = make_rng(seed + seed_offset).py_rng
        return int(rng.choice(candidates))
    raise ValueError(f"Unsupported total_sru method: {method}")


def _split_total_sru_by_type(total_sru: int, num_types: int, seed: int, method: str) -> List[int]:
    if method != "balanced_min1_randomized":
        raise ValueError(f"Unsupported sru split method: {method}")
    if total_sru < num_types:
        raise ValueError("total_sru must be >= num_types")
    base = total_sru // num_types
    counts = [base for _ in range(num_types)]
    remainder = total_sru - base * num_types
    if remainder > 0:
        rng = make_rng(seed).py_rng
        order = list(range(num_types))
        rng.shuffle(order)
        for idx in order[:remainder]:
            counts[idx] += 1
    if min(counts) <= 0:
        raise ValueError("invalid SRU split: each type must have at least one SRU")
    return counts


def _assign_job_types_balanced(job_ids: List[int], num_types: int, seed: int) -> Dict[int, int]:
    rng = make_rng(seed).py_rng
    shuffled = list(job_ids)
    rng.shuffle(shuffled)
    out: Dict[int, int] = {}
    for idx, j in enumerate(shuffled):
        out[j] = (idx % num_types) + 1
    return out


def _random_machine_subset(num_machines: int, ratio_range: Tuple[float, float], seed: int) -> set[int]:
    rng = make_rng(seed).py_rng
    all_machines = list(range(1, num_machines + 1))
    low, high = ratio_range
    low = max(0.1, float(low))
    high = min(1.0, float(high))
    if high < low:
        high = low
    low_n = max(1, int(math.ceil(low * num_machines)))
    high_n = max(low_n, int(math.ceil(high * num_machines)))
    target_n = rng.randint(low_n, high_n)
    target_n = min(target_n, num_machines)
    rng.shuffle(all_machines)
    return set(all_machines[:target_n])


def _build_machine_sets_for_type(
    num_machines: int,
    num_srus: int,
    ratio_range: Tuple[float, float],
    seed: int,
) -> List[List[int]]:
    if num_srus <= 0:
        return []
    rng = make_rng(seed).py_rng
    machine_sets: List[set[int]] = [
        _random_machine_subset(num_machines=num_machines, ratio_range=ratio_range, seed=seed + 17 * i)
        for i in range(num_srus)
    ]

    # Ensure the union covers all machines for same-type global feasibility.
    all_machines = list(range(1, num_machines + 1))
    rng.shuffle(all_machines)
    for idx, machine_id in enumerate(all_machines):
        machine_sets[idx % num_srus].add(machine_id)

    # Enforce non-identical sets whenever it is structurally possible.
    if num_srus > 1 and num_machines > 1:
        attempts = 0
        while len({tuple(sorted(mset)) for mset in machine_sets}) == 1 and attempts < 24:
            target = machine_sets[-1]
            missing = [m for m in range(1, num_machines + 1) if m not in target]
            removable = [m for m in target if len(target) > 1 and sum(1 for ms in machine_sets if m in ms) > 1]
            if missing and (not removable or rng.random() < 0.6):
                target.add(rng.choice(missing))
            elif removable:
                target.remove(rng.choice(removable))
            attempts += 1

    return [sorted(mset) for mset in machine_sets]


def _job_compatible(machine_set: set[int], op_candidates: List[set[int]]) -> bool:
    return all(len(machine_set & cset) > 0 for cset in op_candidates)


def _type_has_feasible_job_assignment(machine_sets: List[set[int]], jobs_candidates: List[List[set[int]]]) -> bool:
    for job_candidates in jobs_candidates:
        if not any(_job_compatible(mset, job_candidates) for mset in machine_sets):
            return False
    return True


def _build_srus_nonidentical(
    mk: MKInstance,
    job_type: Dict[int, int],
    num_types: int,
    sru_count_by_type: List[int],
    ratio_range: Tuple[float, float],
    seed: int,
) -> List[SRU]:
    srus: List[SRU] = []
    sid = 1
    rng = make_rng(seed).py_rng
    jobs_candidates_by_type: Dict[int, List[List[set[int]]]] = {t: [] for t in range(1, num_types + 1)}
    for mk_job in mk.jobs:
        t = job_type[mk_job.job_id]
        jobs_candidates_by_type[t].append([{m for m, _ in mk_op.options} for mk_op in mk_job.operations])

    for t in range(1, num_types + 1):
        machine_sets = [
            set(mset)
            for mset in _build_machine_sets_for_type(
                num_machines=mk.num_machines,
                num_srus=sru_count_by_type[t - 1],
                ratio_range=ratio_range,
                seed=seed + t * 1000,
            )
        ]
        for job_candidates in jobs_candidates_by_type[t]:
            if any(_job_compatible(mset, job_candidates) for mset in machine_sets):
                continue
            target_idx = min(range(len(machine_sets)), key=lambda i: len(machine_sets[i]))
            target = machine_sets[target_idx]
            for cset in job_candidates:
                if not (target & cset):
                    target.add(rng.choice(sorted(cset)))

        if len(machine_sets) > 1 and len({tuple(sorted(x)) for x in machine_sets}) == 1:
            base = set(machine_sets[-1])
            for _ in range(32):
                candidate = set(base)
                missing = [m for m in range(1, mk.num_machines + 1) if m not in candidate]
                removable = [m for m in candidate if len(candidate) > 1 and sum(1 for ms in machine_sets if m in ms) > 1]
                if missing and (not removable or rng.random() < 0.6):
                    candidate.add(rng.choice(missing))
                elif removable:
                    candidate.remove(rng.choice(removable))
                else:
                    break
                if candidate == base:
                    continue
                trial = list(machine_sets)
                trial[-1] = candidate
                if _type_has_feasible_job_assignment(trial, jobs_candidates_by_type[t]):
                    machine_sets[-1] = candidate
                    break

        for mset in machine_sets:
            srus.append(SRU(sru_id=sid, type_id=t, machine_ids=sorted(mset)))
            sid += 1

    return srus


def convert_mk_to_sdmk(mk: MKInstance, spec: DatasetSpec, seed_offset: int = 0) -> SMDFJSPInstance:
    local_seed = spec.seed + seed_offset
    rng = make_rng(local_seed)
    if spec.type_assignment != "balanced_shuffle":
        raise ValueError(f"Unsupported type assignment: {spec.type_assignment}")

    job_ids = [j.job_id for j in mk.jobs]
    job_type = _assign_job_types_balanced(job_ids, spec.num_types, local_seed)
    total_sru = _choose_total_sru(
        candidates=spec.total_sru_candidates,
        seed=spec.seed,
        seed_offset=seed_offset,
        method=spec.total_sru_method,
    )
    sru_count_by_type = _split_total_sru_by_type(
        total_sru=total_sru,
        num_types=spec.num_types,
        seed=local_seed + 7919,
        method=spec.sru_split_method,
    )
    srus = _build_srus_nonidentical(
        mk=mk,
        job_type=job_type,
        num_types=spec.num_types,
        sru_count_by_type=sru_count_by_type,
        ratio_range=spec.sru_machine_ratio_range,
        seed=local_seed,
    )
    srus_by_type: Dict[int, List[SRU]] = {}
    for s in srus:
        srus_by_type.setdefault(s.type_id, []).append(s)

    # Processing-time efficiency factor per (sru, machine)
    low_f, high_f = spec.process_time_factor_range
    factor: Dict[Tuple[int, int], float] = {}
    for s in srus:
        for m in s.machine_ids:
            factor[(s.sru_id, m)] = float(rng.np_rng.uniform(low_f, high_f))

    jobs: List[Job] = []
    for mk_job in mk.jobs:
        t = job_type[mk_job.job_id]
        type_srus = srus_by_type[t]
        operations: List[Operation] = []
        for op_idx, mk_op in enumerate(mk_job.operations, start=1):
            options: List[ProcessOption] = []
            for s in type_srus:
                for machine_id, base_pt in mk_op.options:
                    if machine_id not in s.machine_ids:
                        continue
                    if (s.sru_id, machine_id) not in factor:
                        factor[(s.sru_id, machine_id)] = float(rng.np_rng.uniform(low_f, high_f))
                    pt = max(1, int(round(base_pt * factor[(s.sru_id, machine_id)])))
                    cp = int(rng.np_rng.integers(spec.process_cost_range[0], spec.process_cost_range[1] + 1))
                    options.append(
                        ProcessOption(
                            sru_id=s.sru_id,
                            machine_id=machine_id,
                            process_time=pt,
                            process_cost_per_time=cp,
                        )
                    )
            # Safety fallback: keep operation globally feasible in the same job type.
            if not options:
                machine_id, base_pt = min(mk_op.options, key=lambda x: x[1])
                s = type_srus[0]
                if machine_id not in s.machine_ids:
                    s.machine_ids.append(machine_id)
                    s.machine_ids.sort()
                if (s.sru_id, machine_id) not in factor:
                    factor[(s.sru_id, machine_id)] = float(rng.np_rng.uniform(low_f, high_f))
                pt = max(1, int(round(base_pt * factor[(s.sru_id, machine_id)])))
                cp = int(rng.np_rng.integers(spec.process_cost_range[0], spec.process_cost_range[1] + 1))
                options.append(
                    ProcessOption(
                        sru_id=s.sru_id,
                        machine_id=machine_id,
                        process_time=pt,
                        process_cost_per_time=cp,
                    )
                )
            operations.append(Operation(op_id=op_idx, options=options))
        jobs.append(Job(job_id=mk_job.job_id, type_id=t, operations=operations))

    t_time: Dict[Tuple[int, int], int] = {}
    t_cost: Dict[Tuple[int, int], int] = {}
    for job in jobs:
        for s in srus_by_type[job.type_id]:
            t_time[(job.job_id, s.sru_id)] = int(
                rng.np_rng.integers(spec.transport_time_range[0], spec.transport_time_range[1] + 1)
            )
            t_cost[(job.job_id, s.sru_id)] = int(
                rng.np_rng.integers(spec.transport_cost_range[0], spec.transport_cost_range[1] + 1)
            )

    return SMDFJSPInstance(
        name=f"sd{mk.name}",
        num_types=spec.num_types,
        jobs=jobs,
        srus=srus,
        transport_time=t_time,
        transport_cost_per_time=t_cost,
        metadata={
            "source_mk": mk.name,
            "seed": local_seed,
            "num_machines_mk": mk.num_machines,
            "total_sru_candidates": spec.total_sru_candidates,
            "total_sru_method": spec.total_sru_method,
            "total_sru": total_sru,
            "sru_split_method": spec.sru_split_method,
            "sru_split_by_type": sru_count_by_type,
            "assumption_machine_policy": "typewise_nonidentical_machine_subsets_with_global_feasibility_guard",
            "sru_machine_ratio_range": spec.sru_machine_ratio_range,
            "assumption_type_assignment": spec.type_assignment,
        },
    )


def build_sdmk_dataset(
    mk_dir: str | Path,
    spec_path: str | Path,
    output_dir: str | Path,
    manifest_path: str | Path,
) -> None:
    mk_dir = Path(mk_dir)
    root_dir = mk_dir.parent
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    spec = load_dataset_spec(spec_path)

    mk_files = sorted(mk_dir.glob("mk*.txt"))
    rows: List[Dict[str, object]] = []
    for idx, mk_file in enumerate(mk_files):
        mk = parse_mk_file(mk_file)
        inst = convert_mk_to_sdmk(mk, spec, seed_offset=idx)
        out_file = output_dir / f"{inst.name}.json"
        save_instance_json(inst, out_file)
        rel_out = out_file.relative_to(root_dir).as_posix() if out_file.is_absolute() else out_file.as_posix()
        total_ops = sum(len(j.operations) for j in inst.jobs)
        total_options = sum(len(op.options) for j in inst.jobs for op in j.operations)
        rows.append(
            {
                "instance": inst.name,
                "source_mk": mk.name,
                "jobs": len(inst.jobs),
                "types": inst.num_types,
                "srus": len(inst.srus),
                "ops": total_ops,
                "options": total_options,
                "seed": inst.metadata["seed"],
                "file": rel_out,
            }
        )
    with Path(manifest_path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["instance", "source_mk", "jobs", "types", "srus", "ops", "options", "seed", "file"]
        )
        writer.writeheader()
        writer.writerows(rows)


def generate_release_time_map(
    job_ids: Sequence[int],
    seed: int,
    initial_job_ratio: float,
    arrival_time_range: Tuple[int, int],
    step: int = 1,
) -> Tuple[Dict[int, float], List[int]]:
    """
    Generate release_time for dynamic conversion:
    - a subset of jobs starts at t=0
    - others arrive later in [min_t, max_t], snapped by step
    """
    if not job_ids:
        return {}, []
    rng = make_rng(seed).py_rng
    ids = list(job_ids)
    rng.shuffle(ids)
    n = len(ids)
    ratio = max(0.0, min(1.0, float(initial_job_ratio)))
    n0 = int(round(n * ratio))
    n0 = max(1, min(n, n0))
    initial = sorted(ids[:n0])
    future = ids[n0:]
    t_low, t_high = int(arrival_time_range[0]), int(arrival_time_range[1])
    if t_high < t_low:
        t_high = t_low
    step = max(1, int(step))
    rel: Dict[int, float] = {j: 0.0 for j in initial}
    for j in future:
        t = rng.randint(t_low, t_high)
        t = (t // step) * step
        rel[j] = float(max(step, t))
    return rel, initial


def convert_static_instance_to_dynamic(
    instance: SMDFJSPInstance,
    release_time_by_job: Dict[int, float],
    initial_jobs: Optional[List[int]] = None,
    dynamic_tag: str = "dynamic_release_time",
) -> SMDFJSPInstance:
    jobs: List[Job] = []
    for job in instance.jobs:
        jobs.append(
            Job(
                job_id=job.job_id,
                type_id=job.type_id,
                operations=list(job.operations),
                release_time=float(release_time_by_job.get(job.job_id, 0.0)),
            )
        )
    if initial_jobs is None:
        init = sorted(j.job_id for j in jobs if j.release_time <= 0.0)
    else:
        init = sorted({int(x) for x in initial_jobs})
    arrival_stream = build_arrival_stream_from_release_time(jobs)
    metadata = dict(instance.metadata)
    metadata["dynamic_tag"] = dynamic_tag
    metadata["release_time_source"] = "job.release_time"
    metadata["arrival_stream_source"] = "derived_from_release_time"
    return SMDFJSPInstance(
        name=instance.name,
        num_types=instance.num_types,
        jobs=jobs,
        srus=list(instance.srus),
        transport_time=dict(instance.transport_time),
        transport_cost_per_time=dict(instance.transport_cost_per_time),
        metadata=metadata,
        initial_jobs=init,
        arrival_stream=arrival_stream,
    )

