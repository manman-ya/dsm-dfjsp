from __future__ import annotations

from typing import Dict, List, Set, Tuple

from smdfjsp.core.types import DecodeContext, RollingState, SMDFJSPInstance, ScheduleRecord
from smdfjsp.data.io import build_arrival_stream_from_release_time


def build_arrival_stream_index(instance: SMDFJSPInstance) -> Dict[float, List[int]]:
    by_time: Dict[float, List[int]] = {}
    for event in build_arrival_stream_from_release_time(instance.jobs):
        by_time[float(event.time)] = list(event.job_ids)
    return by_time


def initialize_rolling_state(instance: SMDFJSPInstance, start_time: float = 0.0) -> RollingState:
    state = RollingState(current_time=float(start_time))
    state.arrival_stream_index = build_arrival_stream_index(instance)
    for job in instance.jobs:
        state.completed_ops_by_job[job.job_id] = 0
        state.job_ready[job.job_id] = max(float(start_time), float(job.release_time))
        if job.release_time <= start_time:
            state.active_jobs.add(job.job_id)
        else:
            state.future_jobs.add(job.job_id)
    return state


def _record_exists(records: List[ScheduleRecord], rec: ScheduleRecord) -> bool:
    key = (rec.job_id, rec.op_id, rec.sru_id, rec.machine_id, rec.start, rec.end)
    for x in records:
        if (x.job_id, x.op_id, x.sru_id, x.machine_id, x.start, x.end) == key:
            return True
    return False


def freeze_completed_record(state: RollingState, rec: ScheduleRecord) -> None:
    if not _record_exists(state.frozen_records, rec):
        state.frozen_records.append(rec)
    state.completed_ops_by_job[rec.job_id] = max(state.completed_ops_by_job.get(rec.job_id, 0), rec.op_id)
    state.machine_ready[(rec.sru_id, rec.machine_id)] = max(
        state.machine_ready.get((rec.sru_id, rec.machine_id), 0.0),
        float(rec.end),
    )
    state.job_ready[rec.job_id] = max(state.job_ready.get(rec.job_id, 0.0), float(rec.end))


def settle_in_progress_until(instance: SMDFJSPInstance, state: RollingState, time_point: float) -> None:
    # Move finished in-progress operations into completed/frozen set.
    done_keys: List[Tuple[int, int]] = []
    for key, ip in state.in_progress_ops.items():
        state.machine_ready[(ip.sru_id, ip.machine_id)] = max(
            state.machine_ready.get((ip.sru_id, ip.machine_id), 0.0),
            float(ip.expected_end_time),
        )
        state.job_ready[ip.job_id] = max(state.job_ready.get(ip.job_id, 0.0), float(ip.expected_end_time))
        if float(ip.expected_end_time) <= float(time_point):
            freeze_completed_record(
                state,
                ScheduleRecord(
                    job_id=ip.job_id,
                    op_id=ip.op_id,
                    sru_id=ip.sru_id,
                    machine_id=ip.machine_id,
                    start=float(ip.start_time),
                    end=float(ip.expected_end_time),
                ),
            )
            done_keys.append(key)
    for key in done_keys:
        state.in_progress_ops.pop(key, None)
    refresh_job_sets(instance, state, time_point=float(time_point))


def refresh_job_sets(instance: SMDFJSPInstance, state: RollingState, time_point: float) -> None:
    state.current_time = float(time_point)
    state.active_jobs.clear()
    state.future_jobs.clear()
    state.completed_jobs.clear()
    for job in instance.jobs:
        completed = int(state.completed_ops_by_job.get(job.job_id, 0))
        if completed >= len(job.operations):
            state.completed_jobs.add(job.job_id)
            continue
        if float(job.release_time) <= float(time_point):
            state.active_jobs.add(job.job_id)
        else:
            state.future_jobs.add(job.job_id)


def build_decode_context(instance: SMDFJSPInstance, state: RollingState) -> DecodeContext:
    eligible = set(state.active_jobs) - set(state.completed_jobs)
    return DecodeContext(
        current_time=float(state.current_time),
        eligible_job_ids=eligible,
        completed_ops_by_job=dict(state.completed_ops_by_job),
        in_progress_ops=dict(state.in_progress_ops),
        frozen_job_ready=dict(state.job_ready),
        frozen_machine_ready=dict(state.machine_ready),
        frozen_records=list(state.frozen_records),
        frozen_ua_by_job=dict(state.frozen_ua_by_job),
        include_transport_for_incomplete_jobs=False,
    )
