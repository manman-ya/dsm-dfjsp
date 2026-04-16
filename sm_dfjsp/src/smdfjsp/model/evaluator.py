from __future__ import annotations

# Unified objective evaluator:
# - validates encoding
# - simulates operation scheduling
# - adds transport time/cost
# - returns (total_cost, makespan)

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from smdfjsp.core.encoding import build_option_index
from smdfjsp.core.types import DecodeContext, EncodedIndividual, ObjPair, ScheduleRecord, SMDFJSPInstance


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


def _in_progress_by_job(ctx: Optional[DecodeContext]) -> Dict[int, int]:
    if ctx is None:
        return {}
    out: Dict[int, int] = {}
    for rec in ctx.in_progress_ops.values():
        out[rec.job_id] = rec.op_id
    return out


def _expected_os_count_by_job(instance: SMDFJSPInstance, ctx: Optional[DecodeContext]) -> Dict[int, int]:
    expected: Dict[int, int] = {}
    in_progress = _in_progress_by_job(ctx)
    eligible: Set[int] = set(ctx.eligible_job_ids) if (ctx and ctx.eligible_job_ids) else {j.job_id for j in instance.jobs}
    for job in instance.jobs:
        if job.job_id not in eligible:
            continue
        completed = ctx.completed_ops_by_job.get(job.job_id, 0) if ctx else 0
        started_offset = completed + (1 if job.job_id in in_progress else 0)
        remain = max(len(job.operations) - started_offset, 0)
        if remain > 0:
            expected[job.job_id] = remain
    return expected


def validate_os(instance: SMDFJSPInstance, os_layer: Dict[int, List[int]], ctx: Optional[DecodeContext] = None) -> bool:
    # Check that each job appears in OS exactly as many times as its expected op count.
    expected_by_job = _expected_os_count_by_job(instance, ctx)
    for t in range(1, instance.num_types + 1):
        expected: Dict[int, int] = {}
        for job in instance.jobs:
            if job.type_id == t and expected_by_job.get(job.job_id, 0) > 0:
                expected[job.job_id] = expected_by_job[job.job_id]
        got: Dict[int, int] = {}
        for j in os_layer.get(t, []):
            got[j] = got.get(j, 0) + 1
        if expected != got:
            return False
    return True


def _seed_cost_from_records(
    records: List[ScheduleRecord],
    option_index: Dict[Tuple[int, int, int], Dict[int, Tuple[int, int]]],
) -> float:
    total = 0.0
    for rec in records:
        m_dict = option_index.get((rec.job_id, rec.op_id, rec.sru_id), {})
        if rec.machine_id in m_dict:
            pt, cp = m_dict[rec.machine_id]
            total += float(pt * cp)
    return total


def evaluate_individual(
    instance: SMDFJSPInstance,
    individual: EncodedIndividual,
    ctx: Optional[DecodeContext] = None,
) -> EvalResult:
    # Build option lookup for fast machine feasibility checks.
    option_index = build_option_index(instance)
    # Reject invalid OS token multiset immediately.
    if not validate_os(instance, individual.os, ctx=ctx):
        return EvalResult((float("inf"), float("inf")), feasible=False, records=[], message="invalid OS multiset")

    # Build OP if absent.
    if not individual.op:
        if ctx is None:
            from smdfjsp.core.encoding import op_from_ua_os

            individual.op = op_from_ua_os(instance, individual.ua, individual.os)
        else:
            from smdfjsp.core.encoding import op_from_ua_os_remaining

            in_progress = _in_progress_by_job(ctx)
            individual.op = op_from_ua_os_remaining(
                instance=instance,
                ua_layer=individual.ua,
                os_layer=individual.os,
                completed_ops_by_job=ctx.completed_ops_by_job,
                in_progress_op_by_job=in_progress,
                eligible_job_ids=ctx.eligible_job_ids,
            )

    # Readiness states in schedule simulation.
    in_progress = _in_progress_by_job(ctx)
    machine_ready: Dict[Tuple[int, int], float] = dict(ctx.frozen_machine_ready) if ctx else {}
    job_ready: Dict[int, float] = {}
    for j in instance.jobs:
        if ctx is None:
            job_ready[j.job_id] = 0.0
        else:
            job_ready[j.job_id] = max(
                float(j.release_time),
                float(ctx.frozen_job_ready.get(j.job_id, 0.0)),
                float(ctx.current_time),
            )
    records: List[ScheduleRecord] = list(ctx.frozen_records) if ctx else []
    total_cost = _seed_cost_from_records(records, option_index) if ctx else 0.0
    feasible = True
    scheduled_ops_by_job: Dict[int, int] = {}

    if ctx:
        for rec in ctx.in_progress_ops.values():
            machine_key = (rec.sru_id, rec.machine_id)
            machine_ready[machine_key] = max(machine_ready.get(machine_key, 0.0), float(rec.expected_end_time))
            job_ready[rec.job_id] = max(job_ready.get(rec.job_id, 0.0), float(rec.expected_end_time))

    # Decode OP/MS into concrete start/end times.
    release_time_by_job = {j.job_id: float(j.release_time) for j in instance.jobs}
    eligible_jobs = set(ctx.eligible_job_ids) if (ctx and ctx.eligible_job_ids) else None
    for sru_id, seq in individual.op.items():
        ms_vec = individual.ms.get(sru_id, [])
        for idx, (job_id, op_id) in enumerate(seq):
            if eligible_jobs is not None and job_id not in eligible_jobs:
                feasible = False
                continue
            if ctx:
                completed = int(ctx.completed_ops_by_job.get(job_id, 0))
                if op_id <= completed:
                    # Already completed in frozen prefix.
                    continue
                if in_progress.get(job_id) == op_id:
                    # Currently in-progress and non-preemptive.
                    continue
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
            base_t = ctx.current_time if ctx else 0.0
            start = max(
                job_ready.get(job_id, 0.0),
                machine_ready.get((sru_id, chosen), 0.0),
                release_time_by_job.get(job_id, 0.0),
                float(base_t),
            )
            end = start + pt
            job_ready[job_id] = end
            machine_ready[(sru_id, chosen)] = end
            total_cost += pt * cp
            scheduled_ops_by_job[job_id] = scheduled_ops_by_job.get(job_id, 0) + 1
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
    if eligible_jobs is None:
        job_scope = [j.job_id for j in instance.jobs]
    else:
        job_scope = sorted(eligible_jobs)
    for job_id in job_scope:
        complete_time = job_ready.get(job_id, 0.0)
        sru_id = individual.ua.get(job_id)
        if ctx and job_id in ctx.frozen_ua_by_job:
            frozen_sid = ctx.frozen_ua_by_job[job_id]
            if sru_id is None:
                sru_id = frozen_sid
            elif sru_id != frozen_sid:
                return EvalResult(
                    (float("inf"), float("inf")),
                    feasible=False,
                    records=records,
                    message="frozen ua mismatch",
                )
        if sru_id is None:
            return EvalResult((float("inf"), float("inf")), feasible=False, records=records, message="ua miss")
        # Hard type-consistency constraint.
        if sru_map[sru_id].type_id != job_map[job_id].type_id:
            feasible = False
            return EvalResult((float("inf"), float("inf")), feasible=False, records=records, message="type mismatch")

        if ctx:
            total_ops = len(job_map[job_id].operations)
            completed = int(ctx.completed_ops_by_job.get(job_id, 0))
            started = completed + (1 if job_id in in_progress else 0)
            planned = int(scheduled_ops_by_job.get(job_id, 0))
            if started + planned < total_ops and not ctx.include_transport_for_incomplete_jobs:
                feasible = False
                continue

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

