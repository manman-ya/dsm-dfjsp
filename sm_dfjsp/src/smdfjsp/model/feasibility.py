from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from smdfjsp.core.types import SMDFJSPInstance, ScheduleRecord


@dataclass(frozen=True)
class FeasibilityViolation:
    code: str
    message: str


@dataclass(frozen=True)
class FeasibilityReport:
    feasible: bool
    violations: List[FeasibilityViolation]


def check_schedule_feasibility(
    instance: SMDFJSPInstance,
    records: List[ScheduleRecord],
    require_complete: bool = True,
    eps: float = 1e-9,
) -> FeasibilityReport:
    violations: List[FeasibilityViolation] = []
    job_map = instance.job_map()

    valid_options: Dict[Tuple[int, int], set[Tuple[int, int]]] = {}
    for job in instance.jobs:
        for op in job.operations:
            valid_options[(job.job_id, op.op_id)] = {(opt.sru_id, opt.machine_id) for opt in op.options}

    by_job_op: Dict[Tuple[int, int], List[ScheduleRecord]] = {}
    by_machine: Dict[Tuple[int, int], List[ScheduleRecord]] = {}

    for rec in records:
        if rec.end <= rec.start + eps:
            violations.append(
                FeasibilityViolation(
                    code="invalid_duration",
                    message=(
                        f"Invalid duration job={rec.job_id}, op={rec.op_id}, "
                        f"start={rec.start:.6f}, end={rec.end:.6f}"
                    ),
                )
            )

        if rec.job_id not in job_map:
            violations.append(
                FeasibilityViolation(code="unknown_job", message=f"Unknown job in record: job={rec.job_id}")
            )
            continue
        if rec.op_id < 1 or rec.op_id > len(job_map[rec.job_id].operations):
            violations.append(
                FeasibilityViolation(
                    code="unknown_operation",
                    message=f"Unknown op in record: job={rec.job_id}, op={rec.op_id}",
                )
            )
            continue

        key = (rec.job_id, rec.op_id)
        if (rec.sru_id, rec.machine_id) not in valid_options.get(key, set()):
            violations.append(
                FeasibilityViolation(
                    code="invalid_machine_assignment",
                    message=(
                        f"Operation assigned to infeasible machine: job={rec.job_id}, op={rec.op_id}, "
                        f"sru={rec.sru_id}, machine={rec.machine_id}"
                    ),
                )
            )

        if rec.start + eps < float(job_map[rec.job_id].release_time):
            violations.append(
                FeasibilityViolation(
                    code="early_start_before_release",
                    message=(
                        f"Dynamic job starts before release: job={rec.job_id}, op={rec.op_id}, "
                        f"start={rec.start:.6f}, release={float(job_map[rec.job_id].release_time):.6f}"
                    ),
                )
            )

        by_job_op.setdefault(key, []).append(rec)
        by_machine.setdefault((rec.sru_id, rec.machine_id), []).append(rec)

    # Each operation must be assigned exactly once.
    for job in instance.jobs:
        for op in job.operations:
            key = (job.job_id, op.op_id)
            cnt = len(by_job_op.get(key, []))
            if cnt == 0 and require_complete:
                violations.append(
                    FeasibilityViolation(
                        code="missing_operation_assignment",
                        message=f"Missing assignment: job={job.job_id}, op={op.op_id}",
                    )
                )
            elif cnt > 1:
                violations.append(
                    FeasibilityViolation(
                        code="duplicate_operation_assignment",
                        message=f"Duplicate assignment: job={job.job_id}, op={op.op_id}, count={cnt}",
                    )
                )

    # Operation precedence within each job.
    for job in instance.jobs:
        n_ops = len(job.operations)
        for op_id in range(2, n_ops + 1):
            prev_recs = by_job_op.get((job.job_id, op_id - 1), [])
            cur_recs = by_job_op.get((job.job_id, op_id), [])
            if len(prev_recs) != 1 or len(cur_recs) != 1:
                continue
            prev = prev_recs[0]
            cur = cur_recs[0]
            if cur.start + eps < prev.end:
                violations.append(
                    FeasibilityViolation(
                        code="operation_order_violation",
                        message=(
                            f"Operation order violated: job={job.job_id}, "
                            f"op{op_id-1}_end={prev.end:.6f} > op{op_id}_start={cur.start:.6f}"
                        ),
                    )
                )

    # No overlap on each machine timeline.
    for machine_key, m_recs in by_machine.items():
        ordered = sorted(m_recs, key=lambda x: (x.start, x.end, x.job_id, x.op_id))
        latest_end = float("-inf")
        latest_rec: ScheduleRecord | None = None
        for rec in ordered:
            if latest_rec is not None and rec.start + eps < latest_end:
                violations.append(
                    FeasibilityViolation(
                        code="machine_overlap",
                        message=(
                            f"Machine overlap on (sru={machine_key[0]}, machine={machine_key[1]}): "
                            f"[job={latest_rec.job_id},op={latest_rec.op_id},"
                            f"{latest_rec.start:.6f}-{latest_rec.end:.6f}] vs "
                            f"[job={rec.job_id},op={rec.op_id},{rec.start:.6f}-{rec.end:.6f}]"
                        ),
                    )
                )
            if rec.end > latest_end:
                latest_end = rec.end
                latest_rec = rec

    return FeasibilityReport(feasible=(len(violations) == 0), violations=violations)


def assert_schedule_feasible(
    instance: SMDFJSPInstance,
    records: List[ScheduleRecord],
    require_complete: bool = True,
    eps: float = 1e-9,
    context: str = "",
    max_show: int = 10,
) -> None:
    report = check_schedule_feasibility(
        instance=instance,
        records=records,
        require_complete=require_complete,
        eps=eps,
    )
    if report.feasible:
        return
    head = f"Schedule infeasible{f' ({context})' if context else ''}: {len(report.violations)} violation(s)"
    lines = [head]
    for v in report.violations[:max_show]:
        lines.append(f"- [{v.code}] {v.message}")
    if len(report.violations) > max_show:
        lines.append(f"- ... {len(report.violations) - max_show} more violation(s)")
    raise ValueError("\n".join(lines))

