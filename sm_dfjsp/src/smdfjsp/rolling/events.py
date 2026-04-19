from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from smdfjsp.core.types import RollingConfig, RollingState


EVENT_ARRIVAL = "arrival"
EVENT_PERIODIC = "periodic"
EVENT_MACHINE_IDLE = "machine_idle"
EVENT_OP_FINISH = "op_finish"


@dataclass(order=True)
class RollingEvent:
    time: float
    event_type: str
    job_ids: List[int] = field(default_factory=list, compare=False)


def arrivals_at_time(state: RollingState, time_point: float, eps: float = 1e-9) -> List[int]:
    for t, jobs in state.arrival_stream_index.items():
        if abs(float(t) - float(time_point)) <= eps:
            return list(jobs)
    return []


def is_periodic_time(time_point: float, interval: float, eps: float = 1e-9) -> bool:
    if interval <= 0:
        return False
    q = float(time_point) / float(interval)
    return abs(q - round(q)) <= eps


def next_arrival_event(state: RollingState, after_time: float) -> Optional[RollingEvent]:
    candidates = [t for t in state.arrival_stream_index.keys() if t > float(after_time)]
    if not candidates:
        return None
    t = min(candidates)
    return RollingEvent(time=float(t), event_type=EVENT_ARRIVAL, job_ids=list(state.arrival_stream_index[t]))


def next_periodic_time(after_time: float, interval: float) -> float:
    if interval <= 0:
        return float("inf")
    n = int(after_time // interval) + 1
    return float(n * interval)


def next_periodic_event(after_time: float, interval: float) -> Optional[RollingEvent]:
    t = next_periodic_time(after_time=after_time, interval=interval)
    if t == float("inf"):
        return None
    return RollingEvent(time=t, event_type=EVENT_PERIODIC, job_ids=[])


def next_op_finish_event(state: RollingState, after_time: float) -> Optional[RollingEvent]:
    candidates = [float(x.expected_end_time) for x in state.in_progress_ops.values() if float(x.expected_end_time) > float(after_time)]
    if not candidates:
        return None
    return RollingEvent(time=min(candidates), event_type=EVENT_OP_FINISH, job_ids=[])


def should_trigger_reschedule(state: RollingState, cfg: RollingConfig, at_time: float, eps: float = 1e-9) -> bool:
    if cfg.trigger_on_arrival and arrivals_at_time(state, at_time, eps=eps):
        return True
    if cfg.trigger_on_periodic and is_periodic_time(at_time, cfg.periodic_interval, eps=eps):
        return True
    return False


def next_trigger_event(
    state: RollingState,
    cfg: RollingConfig,
    after_time: float,
) -> Optional[RollingEvent]:
    events: List[RollingEvent] = []
    if cfg.trigger_on_arrival:
        e_arr = next_arrival_event(state, after_time=after_time)
        if e_arr is not None:
            events.append(e_arr)
    if cfg.trigger_on_periodic:
        e_p = next_periodic_event(after_time=after_time, interval=cfg.periodic_interval)
        if e_p is not None:
            events.append(e_p)
    if not events:
        return None
    events.sort(key=lambda x: (x.time, x.event_type))
    return events[0]


def next_event_time(
    state: RollingState,
    cfg: RollingConfig,
    after_time: float,
    until_time: float,
) -> float:
    events: List[RollingEvent] = []
    # Arrival and operation-finish are timeline events even if they do not trigger reschedule.
    e_arr = next_arrival_event(state, after_time=after_time)
    if e_arr is not None:
        events.append(e_arr)
    e_fin = next_op_finish_event(state, after_time=after_time)
    if e_fin is not None:
        events.append(e_fin)
    if cfg.trigger_on_periodic:
        e_p = next_periodic_event(after_time=after_time, interval=cfg.periodic_interval)
        if e_p is not None:
            events.append(e_p)
    if not events:
        return float(until_time)
    t = min(x.time for x in events)
    return min(float(until_time), float(t))
