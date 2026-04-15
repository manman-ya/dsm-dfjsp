from __future__ import annotations

# Variation operators shared by multiple baselines.
# Individual representation has four layers: UA / OS / OP / MS.

from copy import deepcopy
from typing import Dict, List, Tuple

from smdfjsp.core.encoding import build_compatible_sru_map, op_from_ua_os, repair_individual, repair_os
from smdfjsp.core.random_utils import RNGPack
from smdfjsp.core.types import EncodedIndividual, SMDFJSPInstance


def crossover(
    p1: EncodedIndividual,
    p2: EncodedIndividual,
    instance: SMDFJSPInstance,
    option_index,
    rng: RNGPack,
) -> EncodedIndividual:
    # Start from an empty child.
    child = EncodedIndividual(ua={}, os={}, op={}, ms={})
    # UA layer: uniform inheritance per job.
    for job in instance.jobs:
        child.ua[job.job_id] = p1.ua[job.job_id] if rng.py_rng.random() < 0.5 else p2.ua[job.job_id]
    # OS layer: single-point recombination by type.
    for t in range(1, instance.num_types + 1):
        v1 = p1.os[t]
        v2 = p2.os[t]
        cp = rng.py_rng.randrange(len(v1)) if v1 else 0
        child.os[t] = v1[:cp] + v2[cp:]
    # Repair OS token counts, then rebuild OP from UA+OS.
    child.os = repair_os(instance, child.os, rng)
    child.op = op_from_ua_os(instance, child.ua, child.os)
    # ms sampled by parental hint where possible.
    for sru_id, seq in child.op.items():
        mvec: List[int] = []
        for i, (job_id, op_id) in enumerate(seq):
            chosen = None
            # Try to inherit machine choice from parents for the same (job, op) in same SRU sequence.
            for src in (p1, p2):
                src_seq = src.op.get(sru_id, [])
                src_ms = src.ms.get(sru_id, [])
                for si, item in enumerate(src_seq):
                    if item == (job_id, op_id) and si < len(src_ms):
                        chosen = src_ms[si]
                        break
                if chosen is not None:
                    break
            options = option_index[(job_id, op_id, sru_id)]
            if chosen not in options:
                # If parental hint is invalid here, fall back to random feasible machine.
                chosen = rng.py_rng.choice(list(options.keys()))
            mvec.append(chosen)
        child.ms[sru_id] = mvec
    # Final consistency repair across all layers.
    return repair_individual(child, instance, option_index, rng)


def mutate(
    ind: EncodedIndividual,
    instance: SMDFJSPInstance,
    option_index,
    rng: RNGPack,
    mr: float,
) -> EncodedIndividual:
    # Work on a copy to keep input immutable.
    out = deepcopy(ind)
    sru_by_type = instance.srus_by_type()
    compatible = build_compatible_sru_map(instance, option_index)
    # UA mutation: reassign job to another compatible SRU.
    for job in instance.jobs:
        if rng.py_rng.random() < mr:
            candidates = compatible.get(job.job_id, [])
            if candidates:
                out.ua[job.job_id] = rng.py_rng.choice(candidates)
            else:
                out.ua[job.job_id] = rng.py_rng.choice(sru_by_type[job.type_id]).sru_id
    # OS mutation: swap two random positions in each type layer.
    for t, vec in out.os.items():
        if len(vec) > 1 and rng.py_rng.random() < mr:
            i, j = rng.py_rng.sample(range(len(vec)), 2)
            vec[i], vec[j] = vec[j], vec[i]
    # Rebuild OP after UA/OS changes.
    out.op = op_from_ua_os(instance, out.ua, out.os)
    # MS mutation: randomly change selected machine assignments.
    for sru_id, seq in out.op.items():
        if sru_id not in out.ms:
            out.ms[sru_id] = []
        # Ensure vector length aligns with OP length.
        while len(out.ms[sru_id]) < len(seq):
            out.ms[sru_id].append(out.ms[sru_id][-1] if out.ms[sru_id] else seq[0][0])
        for i, (job_id, op_id) in enumerate(seq):
            if rng.py_rng.random() < mr:
                options = list(option_index.get((job_id, op_id, sru_id), {}).keys())
                if not options:
                    continue
                out.ms[sru_id][i] = rng.py_rng.choice(options)
    # Final consistency repair across all layers.
    return repair_individual(out, instance, option_index, rng)

