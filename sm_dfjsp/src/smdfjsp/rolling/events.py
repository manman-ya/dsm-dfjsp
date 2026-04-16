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


def next_arrival_event(state: RollingState, after_time: float) -> Optional[RollingEvent]:
    candidates = [t for t in state.arrival_stream_index.keys() if t > after_time]
    if not candidates:
        return None
    t = min(candidates)
    return RollingEvent(time=float(t), event_type=EVENT_ARRIVAL, job_ids=list(state.arrival_stream_index[t]))


def next_periodic_time(after_time: float, interval: float) -> float:
    if interval <= 0:
        return float("inf")
    n = int(after_time // interval) + 1
    return float(n * interval)


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
        t_p = next_periodic_time(after_time=after_time, interval=cfg.periodic_interval)
        if t_p != float("inf"):
            events.append(RollingEvent(time=t_p, event_type=EVENT_PERIODIC, job_ids=[]))
    if not events:
        return None
    events.sort(key=lambda x: (x.time, x.event_type))
    return events[0]
