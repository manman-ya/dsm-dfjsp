from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set, Tuple

from smdfjsp.core.types import (
    InProgressOpRecord,
    Job,
    Operation,
    RollingConfig,
    RollingState,
    SMDFJSPInstance,
    ScheduleRecord,
)
from smdfjsp.rolling.state import (
    freeze_completed_record,
    initialize_rolling_state,
    refresh_job_sets,
    settle_in_progress_until,
)
from smdfjsp.rolling.events import (
    EVENT_ARRIVAL,
    EVENT_PERIODIC,
    arrivals_at_time,
    is_periodic_time,
    next_event_time,
    should_trigger_reschedule,
)


@dataclass
class SubproblemBuildResult:
    instance: SMDFJSPInstance
    op_offset_by_job: Dict[int, int]


def _in_progress_op_by_job(state: RollingState) -> Dict[int, int]:
    out: Dict[int, int] = {}
    for rec in state.in_progress_ops.values():
        out[rec.job_id] = rec.op_id
    return out


def build_remaining_subproblem(instance: SMDFJSPInstance, state: RollingState) -> SubproblemBuildResult:
    """
    Build a static-equivalent subproblem containing only unstarted operations
    for currently eligible jobs (release_time <= t, not completed).
    """
    eligible_jobs: Set[int] = set(state.active_jobs) - set(state.completed_jobs)
    in_progress = _in_progress_op_by_job(state)
    offset_by_job: Dict[int, int] = {}
    sub_jobs: List[Job] = []
    allowed_sru_by_job: Dict[int, Set[int]] = {}
    for job in instance.jobs:
        if job.job_id not in eligible_jobs:
            continue
        completed = int(state.completed_ops_by_job.get(job.job_id, 0))
        started_offset = completed + (1 if job.job_id in in_progress else 0)
        if started_offset >= len(job.operations):
            continue
        offset_by_job[job.job_id] = started_offset
        if job.job_id in state.frozen_ua_by_job:
            allowed_sru_by_job[job.job_id] = {int(state.frozen_ua_by_job[job.job_id])}
        else:
            allowed_sru_by_job[job.job_id] = {s.sru_id for s in instance.srus if s.type_id == job.type_id}

        new_ops: List[Operation] = []
        for local_idx, src_op in enumerate(job.operations[started_offset:], start=1):
            options = [opt for opt in src_op.options if opt.sru_id in allowed_sru_by_job[job.job_id]]
            if not options:
                # Frozen SRU with no remaining option means this subproblem is infeasible by construction.
                raise ValueError(f"No feasible options after UA freeze for job={job.job_id}, op={src_op.op_id}")
            new_ops.append(Operation(op_id=local_idx, options=options))
        sub_jobs.append(
            Job(
                job_id=job.job_id,
                type_id=job.type_id,
                operations=new_ops,
                release_time=max(float(job.release_time), float(state.current_time)),
            )
        )

    sub_transport_time: Dict[Tuple[int, int], int] = {}
    sub_transport_cost: Dict[Tuple[int, int], int] = {}
    for job in sub_jobs:
        allowed = allowed_sru_by_job.get(job.job_id, set())
        for sru_id in allowed:
            key = (job.job_id, sru_id)
            if key in instance.transport_time and key in instance.transport_cost_per_time:
                sub_transport_time[key] = instance.transport_time[key]
                sub_transport_cost[key] = instance.transport_cost_per_time[key]

    sub_instance = SMDFJSPInstance(
        name=f"{instance.name}_rolling_t{int(state.current_time)}",
        num_types=instance.num_types,
        jobs=sub_jobs,
        srus=list(instance.srus),
        transport_time=sub_transport_time,
        transport_cost_per_time=sub_transport_cost,
        metadata={
            **instance.metadata,
            "rolling_subproblem": True,
            "subproblem_time": float(state.current_time),
            "eligible_jobs": sorted(eligible_jobs),
        },
        initial_jobs=[j.job_id for j in sub_jobs if j.release_time <= state.current_time],
        arrival_stream=[],
    )
    return SubproblemBuildResult(instance=sub_instance, op_offset_by_job=offset_by_job)


def lift_records_from_subproblem(
    sub_records: List[ScheduleRecord],
    op_offset_by_job: Dict[int, int],
) -> List[ScheduleRecord]:
    out: List[ScheduleRecord] = []
    for rec in sub_records:
        offset = int(op_offset_by_job.get(rec.job_id, 0))
        out.append(
            ScheduleRecord(
                job_id=rec.job_id,
                op_id=rec.op_id + offset,
                sru_id=rec.sru_id,
                machine_id=rec.machine_id,
                start=float(rec.start),
                end=float(rec.end),
            )
        )
    return out


RescheduleCallback = Callable[[SMDFJSPInstance, RollingState], List[ScheduleRecord]]
PlanValidator = Callable[[SMDFJSPInstance, RollingState, List[ScheduleRecord], float], None]


class RollingScheduler:
    """
    Event-triggered rolling controller.
    Phase-1 default trigger policy:
    - arrival + periodic enabled
    - machine_idle/op_finish reserved but disabled by default.
    """

    def __init__(
        self,
        instance: SMDFJSPInstance,
        callback: RescheduleCallback,
        cfg: RollingConfig | None = None,
        start_time: float = 0.0,
        validator: Optional[PlanValidator] = None,
    ):
        self.instance = instance
        self.callback = callback
        self.validator = validator
        self.cfg = cfg or RollingConfig()
        self.state = initialize_rolling_state(instance, start_time=start_time)

    def _build_trigger_times(self, until_time: float) -> List[float]:
        times: Set[float] = {float(self.state.current_time)}
        if self.cfg.trigger_on_arrival:
            for t in self.state.arrival_stream_index.keys():
                if self.state.current_time <= t <= until_time:
                    times.add(float(t))
        if self.cfg.trigger_on_periodic and self.cfg.periodic_interval > 0:
            t = float(self.state.current_time)
            while t <= until_time:
                times.add(float(t))
                t += float(self.cfg.periodic_interval)
        out = sorted(x for x in times if x <= until_time)
        if not out:
            out = [float(until_time)]
        return out

    def _apply_plan_until(self, plan_records: List[ScheduleRecord], until_time: float) -> None:
        # Freeze finished operations and mark crossing operations as in-progress.
        interval_start = float(self.state.current_time)
        interval_end = float(until_time)
        if interval_end < interval_start:
            return
        # Clear finished in-progress records first.
        settle_in_progress_until(self.instance, self.state, interval_start)
        for rec in sorted(plan_records, key=lambda x: (x.start, x.end)):
            if rec.end <= interval_start:
                continue
            self.state.frozen_ua_by_job.setdefault(rec.job_id, rec.sru_id)
            if rec.start < interval_end and rec.end <= interval_end:
                freeze_completed_record(self.state, rec)
            elif rec.start < interval_end < rec.end:
                key = (rec.job_id, rec.op_id)
                self.state.in_progress_ops[key] = InProgressOpRecord(
                    job_id=rec.job_id,
                    op_id=rec.op_id,
                    sru_id=rec.sru_id,
                    machine_id=rec.machine_id,
                    start_time=float(rec.start),
                    expected_end_time=float(rec.end),
                )
        settle_in_progress_until(self.instance, self.state, interval_end)
        refresh_job_sets(self.instance, self.state, interval_end)

    def run(self, until_time: float) -> RollingState:
        horizon = float(until_time)
        eps = 1e-9
        active_plan_records: List[ScheduleRecord] = []
        first_round = True
        while self.state.current_time < horizon - eps:
            now = float(self.state.current_time)
            settle_in_progress_until(self.instance, self.state, now)
            refresh_job_sets(self.instance, self.state, now)

            trigger_now = first_round or should_trigger_reschedule(self.state, self.cfg, now, eps=eps)
            should_skip_replan = (
                self.state.last_reschedule_time >= 0
                and self.cfg.reschedule_cooldown > 0
                and (now - self.state.last_reschedule_time) < self.cfg.reschedule_cooldown
            )
            did_replan = False
            if trigger_now and not should_skip_replan:
                active_plan_records = self.callback(self.instance, self.state)
                if self.validator is not None:
                    self.validator(self.instance, self.state, active_plan_records, now)
                self.state.current_plan = {"records_count": len(active_plan_records), "trigger_time": now}
                self.state.last_reschedule_time = now
                self.state.reschedule_count += 1
                did_replan = True

            tags: List[str] = []
            if first_round:
                tags.append("initial")
            if arrivals_at_time(self.state, now, eps=eps):
                tags.append(EVENT_ARRIVAL)
            if self.cfg.trigger_on_periodic and is_periodic_time(now, self.cfg.periodic_interval, eps=eps):
                tags.append(EVENT_PERIODIC)
            if did_replan:
                tags.append("reschedule")
            self.state.event_log.append(
                {
                    "time": now,
                    "tags": tags,
                    "active_jobs": len(self.state.active_jobs),
                    "future_jobs": len(self.state.future_jobs),
                    "records_count": len(active_plan_records),
                }
            )

            next_t = next_event_time(
                state=self.state,
                cfg=self.cfg,
                after_time=now,
                until_time=horizon,
            )
            if next_t <= now + eps:
                next_t = horizon
            self._apply_plan_until(active_plan_records, next_t)
            first_round = False

        settle_in_progress_until(self.instance, self.state, horizon)
        refresh_job_sets(self.instance, self.state, horizon)
        return self.state
