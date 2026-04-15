from __future__ import annotations

# Encoding helpers for SM-DFJSP individuals.
# Individual layers:
# - UA: job -> SRU
# - OS: type-wise operation token order
# - OP: per-SRU operation sequence (derived from UA+OS)
# - MS: per-SRU machine sequence aligned with OP

from collections import Counter, defaultdict
from copy import deepcopy
from typing import Dict, List, Tuple

from smdfjsp.core.random_utils import RNGPack
from smdfjsp.core.types import EncodedIndividual, SMDFJSPInstance


def build_option_index(instance: SMDFJSPInstance) -> Dict[Tuple[int, int, int], Dict[int, Tuple[int, int]]]:
    """
    Build index:
    (job_id, op_id, sru_id) -> machine_id -> (process_time, process_cost_per_time)
    """
    idx: Dict[Tuple[int, int, int], Dict[int, Tuple[int, int]]] = {}
    for job in instance.jobs:
        for op in job.operations:
            grouped: Dict[int, Dict[int, Tuple[int, int]]] = defaultdict(dict)
            for opt in op.options:
                # Store machine-level tuple (processing_time, processing_cost_per_time).
                grouped[opt.sru_id][opt.machine_id] = (opt.process_time, opt.process_cost_per_time)
            for sru_id, machine_map in grouped.items():
                idx[(job.job_id, op.op_id, sru_id)] = machine_map
    return idx


def expected_os_multiset(instance: SMDFJSPInstance, type_id: int) -> List[int]:
    # A job id appears as many times as its operation count.
    tokens: List[int] = []
    for job in instance.jobs:
        if job.type_id == type_id:
            tokens.extend([job.job_id] * len(job.operations))
    return tokens


def build_compatible_sru_map(
    instance: SMDFJSPInstance,
    option_index: Dict[Tuple[int, int, int], Dict[int, Tuple[int, int]]],
) -> Dict[int, List[int]]:
    # Compatible means: all operations of this job have at least one machine option on that SRU.
    sru_by_type = instance.srus_by_type()
    out: Dict[int, List[int]] = {}
    for job in instance.jobs:
        candidates: List[int] = []
        for s in sru_by_type[job.type_id]:
            ok = True
            for op in job.operations:
                if (job.job_id, op.op_id, s.sru_id) not in option_index:
                    ok = False
                    break
            if ok:
                candidates.append(s.sru_id)
        if not candidates:
            # Fallback to same-type SRUs to avoid empty choice set.
            candidates = [s.sru_id for s in sru_by_type[job.type_id]]
        out[job.job_id] = candidates
    return out


def random_ua(
    instance: SMDFJSPInstance,
    option_index: Dict[Tuple[int, int, int], Dict[int, Tuple[int, int]]],
    rng: RNGPack,
) -> Dict[int, int]:
    # Randomly assign each job to one compatible SRU.
    sru_by_type = instance.srus_by_type()
    compatible = build_compatible_sru_map(instance, option_index)
    ua: Dict[int, int] = {}
    for job in instance.jobs:
        candidates = compatible.get(job.job_id)
        if candidates:
            ua[job.job_id] = rng.py_rng.choice(candidates)
            continue
        fallback = sru_by_type[job.type_id]
        ua[job.job_id] = rng.py_rng.choice(fallback).sru_id
    return ua


def random_os(instance: SMDFJSPInstance, rng: RNGPack) -> Dict[int, List[int]]:
    # Build and shuffle OS tokens independently for each type.
    out: Dict[int, List[int]] = {}
    for t in range(1, instance.num_types + 1):
        vec = expected_os_multiset(instance, t)
        rng.py_rng.shuffle(vec)
        out[t] = vec
    return out


def repair_os(instance: SMDFJSPInstance, os_layer: Dict[int, List[int]], rng: RNGPack) -> Dict[int, List[int]]:
    # Repair OS so token multiplicities exactly match expected counts.
    out: Dict[int, List[int]] = {}
    for t in range(1, instance.num_types + 1):
        expected = expected_os_multiset(instance, t)
        expected_count = Counter(expected)
        keep: List[int] = []
        current = os_layer.get(t, [])
        for job_id in current:
            if expected_count[job_id] > 0:
                keep.append(job_id)
                expected_count[job_id] -= 1
        missing: List[int] = []
        for job_id, cnt in expected_count.items():
            missing.extend([job_id] * cnt)
        rng.py_rng.shuffle(missing)
        merged = keep + missing
        if len(merged) > len(expected):
            # Trim overflow if any.
            merged = merged[: len(expected)]
        out[t] = merged
    return out


def op_from_ua_os(
    instance: SMDFJSPInstance, ua_layer: Dict[int, int], os_layer: Dict[int, List[int]]
) -> Dict[int, List[Tuple[int, int]]]:
    """
    Build OP layer from UA and OS.
    OP vector item is (job_id, op_id_1based).
    """
    # Pre-create sequence bucket for each SRU.
    op_layer: Dict[int, List[Tuple[int, int]]] = {s.sru_id: [] for s in instance.srus}
    counter_by_job: Dict[int, int] = defaultdict(int)
    job_map = instance.job_map()
    for t in range(1, instance.num_types + 1):
        for job_id in os_layer[t]:
            counter_by_job[job_id] += 1
            op_id = counter_by_job[job_id]
            if op_id <= len(job_map[job_id].operations):
                sru_id = ua_layer[job_id]
                op_layer[sru_id].append((job_id, op_id))
    return op_layer


def random_ms(
    instance: SMDFJSPInstance,
    op_layer: Dict[int, List[Tuple[int, int]]],
    option_index: Dict[Tuple[int, int, int], Dict[int, Tuple[int, int]]],
    rng: RNGPack,
) -> Dict[int, List[int]]:
    # Randomly choose one feasible machine for each OP token.
    ms: Dict[int, List[int]] = {}
    for sru_id, seq in op_layer.items():
        mvec: List[int] = []
        for job_id, op_id in seq:
            choices = list(option_index[(job_id, op_id, sru_id)].keys())
            mvec.append(rng.py_rng.choice(choices))
        ms[sru_id] = mvec
    return ms


def repair_ms(
    instance: SMDFJSPInstance,
    op_layer: Dict[int, List[Tuple[int, int]]],
    ms_layer: Dict[int, List[int]],
    option_index: Dict[Tuple[int, int, int], Dict[int, Tuple[int, int]]],
    rng: RNGPack,
) -> Dict[int, List[int]]:
    # Repair MS to align with OP length and feasible machine sets.
    fixed: Dict[int, List[int]] = {}
    for sru_id, seq in op_layer.items():
        old = ms_layer.get(sru_id, [])
        vec: List[int] = []
        for i, (job_id, op_id) in enumerate(seq):
            options = option_index[(job_id, op_id, sru_id)]
            if i < len(old) and old[i] in options:
                vec.append(old[i])
            else:
                vec.append(rng.py_rng.choice(list(options.keys())))
        fixed[sru_id] = vec
    return fixed


def build_random_individual(
    instance: SMDFJSPInstance,
    option_index: Dict[Tuple[int, int, int], Dict[int, Tuple[int, int]]],
    rng: RNGPack,
) -> EncodedIndividual:
    # Convenience constructor: random UA + random OS + derived OP + random MS.
    ua = random_ua(instance, option_index, rng)
    os_layer = random_os(instance, rng)
    op = op_from_ua_os(instance, ua, os_layer)
    ms = random_ms(instance, op, option_index, rng)
    return EncodedIndividual(ua=ua, os=os_layer, op=op, ms=ms)


def repair_individual(
    individual: EncodedIndividual,
    instance: SMDFJSPInstance,
    option_index: Dict[Tuple[int, int, int], Dict[int, Tuple[int, int]]],
    rng: RNGPack,
) -> EncodedIndividual:
    # Full-layer repair for one individual.
    fixed = deepcopy(individual)
    # UA repair by type consistency.
    sru_by_type = instance.srus_by_type()
    sru_map = instance.sru_map()
    job_map = instance.job_map()
    compatible = build_compatible_sru_map(instance, option_index)
    for job in instance.jobs:
        j_id = job.job_id
        sru_id = fixed.ua.get(j_id)
        type_ok = sru_id in sru_map and sru_map[sru_id].type_id == job_map[j_id].type_id
        compatible_ok = type_ok and sru_id in compatible.get(j_id, [])
        if not compatible_ok:
            candidates = compatible.get(j_id, [])
            if candidates:
                fixed.ua[j_id] = rng.py_rng.choice(candidates)
            else:
                fixed.ua[j_id] = rng.py_rng.choice(sru_by_type[job_map[j_id].type_id]).sru_id
    # Rebuild downstream layers after UA/OS repairs.
    fixed.os = repair_os(instance, fixed.os, rng)
    fixed.op = op_from_ua_os(instance, fixed.ua, fixed.os)
    fixed.ms = repair_ms(instance, fixed.op, fixed.ms, option_index, rng)
    return fixed

