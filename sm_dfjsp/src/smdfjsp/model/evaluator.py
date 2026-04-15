from __future__ import annotations

# Unified objective evaluator:
# - validates encoding
# - simulates operation scheduling
# - adds transport time/cost
# - returns (total_cost, makespan)

from dataclasses import dataclass
from typing import Dict, List, Tuple

from smdfjsp.core.encoding import build_option_index
from smdfjsp.core.types import EncodedIndividual, ObjPair, ScheduleRecord, SMDFJSPInstance


@dataclass
class EvalResult:
    # (total_cost, makespan)
    objectives: ObjPair
    # False means at least one hard constraint violation happened.
    feasible: bool
    # Detailed operation schedule (useful for gantt).
    records: List[ScheduleRecord]
    # Optional reason string for invalid cases.
    message: str = ""


def validate_os(instance: SMDFJSPInstance, os_layer: Dict[int, List[int]]) -> bool:
    # Check that each job appears in OS exactly as many times as its op count.
    for t in range(1, instance.num_types + 1):
        expected: Dict[int, int] = {}
        for job in instance.jobs:
            if job.type_id == t:
                expected[job.job_id] = len(job.operations)
        got: Dict[int, int] = {}
        for j in os_layer.get(t, []):
            got[j] = got.get(j, 0) + 1
        if expected != got:
            return False
    return True


def evaluate_individual(instance: SMDFJSPInstance, individual: EncodedIndividual) -> EvalResult:
    # Build option lookup for fast machine feasibility checks.
    option_index = build_option_index(instance)
    # Reject invalid OS token multiset immediately.
    if not validate_os(instance, individual.os):
        return EvalResult((float("inf"), float("inf")), feasible=False, records=[], message="invalid OS multiset")

    # Build OP if absent.
    if not individual.op:
        from smdfjsp.core.encoding import op_from_ua_os

        individual.op = op_from_ua_os(instance, individual.ua, individual.os)

    # Readiness states in schedule simulation.
    machine_ready: Dict[Tuple[int, int], float] = {}
    job_ready: Dict[int, float] = {j.job_id: 0.0 for j in instance.jobs}
    records: List[ScheduleRecord] = []
    total_cost = 0.0
    feasible = True

    # Decode OP/MS into concrete start/end times.
    for sru_id, seq in individual.op.items():
        ms_vec = individual.ms.get(sru_id, [])
        for idx, (job_id, op_id) in enumerate(seq):
            key = (job_id, op_id, sru_id)
            if key not in option_index:
                feasible = False
                continue
            options = option_index[key]
            chosen = ms_vec[idx] if idx < len(ms_vec) else None
            if chosen not in options:
                # Repair-on-evaluate with fastest feasible machine.
                chosen = min(options.keys(), key=lambda m: options[m][0])
            pt, cp = options[chosen]
            # Operation can start only when both the job and machine are ready.
            start = max(job_ready[job_id], machine_ready.get((sru_id, chosen), 0.0))
            end = start + pt
            job_ready[job_id] = end
            machine_ready[(sru_id, chosen)] = end
            total_cost += pt * cp
            records.append(
                ScheduleRecord(
                    job_id=job_id,
                    op_id=op_id,
                    sru_id=sru_id,
                    machine_id=chosen,
                    start=start,
                    end=end,
                )
            )

    # Add transportation and compute makespan.
    makespan = 0.0
    sru_map = instance.sru_map()
    job_map = instance.job_map()
    for job_id, complete_time in job_ready.items():
        sru_id = individual.ua[job_id]
        # Hard type-consistency constraint.
        if sru_map[sru_id].type_id != job_map[job_id].type_id:
            feasible = False
            return EvalResult((float("inf"), float("inf")), feasible=False, records=records, message="type mismatch")
        t = instance.transport_time.get((job_id, sru_id))
        ct = instance.transport_cost_per_time.get((job_id, sru_id))
        # Transport parameters must exist for each (job, assigned_sru).
        if t is None or ct is None:
            feasible = False
            return EvalResult((float("inf"), float("inf")), feasible=False, records=records, message="transport miss")
        total_cost += t * ct
        makespan = max(makespan, complete_time + t)

    objectives = (float(total_cost), float(makespan))
    return EvalResult(objectives=objectives, feasible=feasible, records=records)

