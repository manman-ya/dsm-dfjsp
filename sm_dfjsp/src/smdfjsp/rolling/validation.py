from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from smdfjsp.core.types import RollingState, ScheduleRecord, SMDFJSPInstance


@dataclass(frozen=True)
class DynamicValidationViolation:
    code: str
    message: str


@dataclass(frozen=True)
class DynamicValidationReport:
    feasible: bool
    violations: List[DynamicValidationViolation]


def _in_progress_records(state: RollingState) -> List[ScheduleRecord]:
    out: List[ScheduleRecord] = []
    for x in state.in_progress_ops.values():
        out.append(
            ScheduleRecord(
                job_id=x.job_id,
                op_id=x.op_id,
                sru_id=x.sru_id,
                machine_id=x.machine_id,
                start=float(x.start_time),
                end=float(x.expected_end_time),
            )
        )
    return out


def _build_allowed_machine_map(instance: SMDFJSPInstance) -> Dict[Tuple[int, int], set[Tuple[int, int]]]:
    allowed: Dict[Tuple[int, int], set[Tuple[int, int]]] = {}
    for job in instance.jobs:
        for op in job.operations:
            allowed[(job.job_id, op.op_id)] = {(opt.sru_id, opt.machine_id) for opt in op.options}
    return allowed


def validate_dynamic_stitching(
    instance: SMDFJSPInstance,
    state: RollingState,
    candidate_records: List[ScheduleRecord],
    trigger_time: float,
    eps: float = 1e-9,
) -> DynamicValidationReport:
    violations: List[DynamicValidationViolation] = []
    frozen = list(state.frozen_records)
    in_progress = _in_progress_records(state)
    combined = frozen + in_progress + list(candidate_records)
    allowed_map = _build_allowed_machine_map(instance)
    job_map = instance.job_map()

    # Machine qualification: candidate ops can only use legal (sru, machine) pairs.
    for rec in candidate_records:
        key = (rec.job_id, rec.op_id)
        if key not in allowed_map:
            violations.append(
                DynamicValidationViolation(
                    code="illegal_machine_assignment",
                    message=f"unknown operation in candidate: job={rec.job_id}, op={rec.op_id}",
                )
            )
            continue
        if (rec.sru_id, rec.machine_id) not in allowed_map[key]:
            violations.append(
                DynamicValidationViolation(
                    code="illegal_machine_assignment",
                    message=(
                        "infeasible machine assignment: "
                        f"job={rec.job_id}, op={rec.op_id}, sru={rec.sru_id}, machine={rec.machine_id}"
                    ),
                )
            )

    # In-progress operation must remain untouched.
    in_progress_keys = {(x.job_id, x.op_id) for x in state.in_progress_ops.values()}
    for rec in candidate_records:
        if (rec.job_id, rec.op_id) in in_progress_keys:
            violations.append(
                DynamicValidationViolation(
                    code="in_progress_changed",
                    message=f"in-progress op appears in candidate: job={rec.job_id}, op={rec.op_id}",
                )
            )

    # Frozen prefix on each machine cannot be changed or overtaken.
    machine_prefix_end: Dict[Tuple[int, int], float] = {}
    for rec in frozen + in_progress:
        key = (rec.sru_id, rec.machine_id)
        machine_prefix_end[key] = max(machine_prefix_end.get(key, float("-inf")), float(rec.end))
    for rec in candidate_records:
        key = (rec.sru_id, rec.machine_id)
        earliest = max(float(trigger_time), machine_prefix_end.get(key, float("-inf")))
        if rec.start + eps < earliest:
            violations.append(
                DynamicValidationViolation(
                    code="frozen_prefix_violation",
                    message=(
                        "candidate operation inserted before frozen prefix end: "
                        f"sru={rec.sru_id}, machine={rec.machine_id}, "
                        f"start={rec.start:.6f}, required>={earliest:.6f}"
                    ),
                )
            )
        if rec.start + eps < max(float(trigger_time), state.machine_ready.get(key, 0.0)):
            violations.append(
                DynamicValidationViolation(
                    code="machine_ready_violation",
                    message=(
                        "operation starts earlier than machine ready time: "
                        f"sru={rec.sru_id}, machine={rec.machine_id}, "
                        f"start={rec.start:.6f}, ready>={max(float(trigger_time), state.machine_ready.get(key, 0.0)):.6f}"
                    ),
                )
            )

    # Single-machine capacity on full stitched timeline.
    by_machine: Dict[Tuple[int, int], List[ScheduleRecord]] = {}
    for rec in combined:
        by_machine.setdefault((rec.sru_id, rec.machine_id), []).append(rec)
    for key, rows in by_machine.items():
        ordered = sorted(rows, key=lambda x: (x.start, x.end, x.job_id, x.op_id))
        latest_end = float("-inf")
        latest_rec: ScheduleRecord | None = None
        for rec in ordered:
            if latest_rec is not None and rec.start + eps < latest_end:
                violations.append(
                    DynamicValidationViolation(
                        code="machine_overlap",
                        message=(
                            f"machine overlap on (sru={key[0]}, machine={key[1]}): "
                            f"[job={latest_rec.job_id},op={latest_rec.op_id},{latest_rec.start:.6f}-{latest_rec.end:.6f}] vs "
                            f"[job={rec.job_id},op={rec.op_id},{rec.start:.6f}-{rec.end:.6f}]"
                        ),
                    )
                )
            latest_end = max(latest_end, rec.end)
            if latest_rec is None or rec.end >= latest_rec.end:
                latest_rec = rec

    # Job precedence consistency on stitched timeline.
    by_job_op: Dict[Tuple[int, int], List[ScheduleRecord]] = {}
    for rec in combined:
        by_job_op.setdefault((rec.job_id, rec.op_id), []).append(rec)
    for job in instance.jobs:
        for op_id in range(1, len(job.operations) + 1):
            rows = by_job_op.get((job.job_id, op_id), [])
            if len(rows) > 1:
                violations.append(
                    DynamicValidationViolation(
                        code="job_precedence_violation",
                        message=f"duplicate assignment after stitching: job={job.job_id}, op={op_id}, count={len(rows)}",
                    )
                )
        for op_id in range(2, len(job.operations) + 1):
            prev = by_job_op.get((job.job_id, op_id - 1), [])
            cur = by_job_op.get((job.job_id, op_id), [])
            if len(prev) != 1 or len(cur) != 1:
                continue
            if cur[0].start + eps < prev[0].end:
                violations.append(
                    DynamicValidationViolation(
                        code="job_precedence_violation",
                        message=(
                            "job precedence broken after stitching: "
                            f"job={job.job_id}, op={op_id-1}->{op_id}, "
                            f"prev_end={prev[0].end:.6f}, cur_start={cur[0].start:.6f}"
                        ),
                    )
                )
            if cur[0].start + eps < float(job_map[job.job_id].release_time):
                violations.append(
                    DynamicValidationViolation(
                        code="job_precedence_violation",
                        message=(
                            f"job starts before release: job={job.job_id}, op={op_id}, "
                            f"start={cur[0].start:.6f}, release={float(job_map[job.job_id].release_time):.6f}"
                        ),
                    )
                )

    return DynamicValidationReport(feasible=(len(violations) == 0), violations=violations)


def assert_dynamic_stitching(
    instance: SMDFJSPInstance,
    state: RollingState,
    candidate_records: List[ScheduleRecord],
    trigger_time: float,
    eps: float = 1e-9,
    context: str = "",
    max_show: int = 10,
) -> None:
    report = validate_dynamic_stitching(
        instance=instance,
        state=state,
        candidate_records=candidate_records,
        trigger_time=trigger_time,
        eps=eps,
    )
    if report.feasible:
        return
    head = f"Dynamic stitching infeasible{f' ({context})' if context else ''}: {len(report.violations)} violation(s)"
    lines = [head]
    for v in report.violations[:max_show]:
        lines.append(f"- [{v.code}] {v.message}")
    if len(report.violations) > max_show:
        lines.append(f"- ... {len(report.violations) - max_show} more violation(s)")
    raise ValueError("\n".join(lines))

