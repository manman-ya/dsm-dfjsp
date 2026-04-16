from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


ObjPair = Tuple[float, float]  # (total_cost, makespan)


@dataclass(frozen=True)
class ProcessOption:
    """One feasible process option of an operation."""

    sru_id: int
    machine_id: int
    process_time: int
    process_cost_per_time: int


@dataclass
class Operation:
    """Operation within one job."""

    op_id: int
    options: List[ProcessOption]


@dataclass
class Job:
    """Job entity."""

    job_id: int
    type_id: int
    operations: List[Operation]
    # Earliest release/arrival time of this job.
    release_time: float = 0.0


@dataclass
class SRU:
    """Service resource unit."""

    sru_id: int
    type_id: int
    machine_ids: List[int]


@dataclass
class SMDFJSPInstance:
    """Full instance used by model and algorithms."""

    name: str
    num_types: int
    jobs: List[Job]
    srus: List[SRU]
    transport_time: Dict[Tuple[int, int], int]
    transport_cost_per_time: Dict[Tuple[int, int], int]
    metadata: Dict[str, object] = field(default_factory=dict)
    # Optional dynamic dataset fields.
    initial_jobs: List[int] = field(default_factory=list)
    arrival_stream: List["ArrivalEvent"] = field(default_factory=list)

    @property
    def num_jobs(self) -> int:
        return len(self.jobs)

    @property
    def num_srus(self) -> int:
        return len(self.srus)

    def jobs_by_type(self) -> Dict[int, List[Job]]:
        grouped: Dict[int, List[Job]] = {}
        for job in self.jobs:
            grouped.setdefault(job.type_id, []).append(job)
        return grouped

    def srus_by_type(self) -> Dict[int, List[SRU]]:
        grouped: Dict[int, List[SRU]] = {}
        for sru in self.srus:
            grouped.setdefault(sru.type_id, []).append(sru)
        return grouped

    def job_map(self) -> Dict[int, Job]:
        return {j.job_id: j for j in self.jobs}

    def sru_map(self) -> Dict[int, SRU]:
        return {s.sru_id: s for s in self.srus}


@dataclass
class EncodedIndividual:
    """Four-layer encoding used by EDA-TS."""

    ua: Dict[int, int]  # job_id -> sru_id
    os: Dict[int, List[int]]  # type_id -> job_id sequence with repetition
    op: Dict[int, List[Tuple[int, int]]]  # sru_id -> sequence of (job_id, op_idx_1based)
    ms: Dict[int, List[int]]  # sru_id -> machine_id sequence aligned with OP
    objectives: Optional[ObjPair] = None
    feasible: Optional[bool] = None
    aux: Dict[str, object] = field(default_factory=dict)


@dataclass
class ScheduleRecord:
    """Decoded schedule record for one operation."""

    job_id: int
    op_id: int
    sru_id: int
    machine_id: int
    start: float
    end: float


@dataclass(frozen=True)
class ArrivalEvent:
    """Auxiliary event index entry derived from jobs' release_time."""

    time: float
    job_ids: List[int]


@dataclass(frozen=True)
class InProgressOpRecord:
    """Non-preemptive operation currently being processed at time t."""

    job_id: int
    op_id: int
    sru_id: int
    machine_id: int
    start_time: float
    expected_end_time: float


@dataclass
class DecodeContext:
    """Context for rolling re-decoding with frozen executed portion."""

    current_time: float
    # Jobs eligible to be scheduled in the current rolling snapshot.
    eligible_job_ids: Set[int] = field(default_factory=set)
    # Number of fully completed operations per job.
    completed_ops_by_job: Dict[int, int] = field(default_factory=dict)
    # In-progress operation records (not completed but frozen).
    in_progress_ops: Dict[Tuple[int, int], InProgressOpRecord] = field(default_factory=dict)
    # Readiness states inherited from frozen prefix.
    frozen_job_ready: Dict[int, float] = field(default_factory=dict)
    frozen_machine_ready: Dict[Tuple[int, int], float] = field(default_factory=dict)
    # Frozen executed records already fixed in timeline.
    frozen_records: List[ScheduleRecord] = field(default_factory=list)
    # Started jobs keep fixed job->SRU assignment.
    frozen_ua_by_job: Dict[int, int] = field(default_factory=dict)
    # In rolling mode, transport terms are counted only for fully completed jobs.
    include_transport_for_incomplete_jobs: bool = False


@dataclass
class RollingConfig:
    """Trigger and horizon policy for rolling rescheduling."""

    trigger_on_arrival: bool = True
    trigger_on_periodic: bool = True
    periodic_interval: float = 10.0
    trigger_on_machine_idle: bool = False
    trigger_on_op_finish: bool = False
    reschedule_cooldown: float = 0.0


@dataclass
class RollingState:
    """State container for event-driven rolling scheduling."""

    current_time: float = 0.0
    active_jobs: Set[int] = field(default_factory=set)
    future_jobs: Set[int] = field(default_factory=set)
    completed_jobs: Set[int] = field(default_factory=set)
    completed_ops_by_job: Dict[int, int] = field(default_factory=dict)
    in_progress_ops: Dict[Tuple[int, int], InProgressOpRecord] = field(default_factory=dict)
    frozen_ua_by_job: Dict[int, int] = field(default_factory=dict)
    machine_ready: Dict[Tuple[int, int], float] = field(default_factory=dict)
    job_ready: Dict[int, float] = field(default_factory=dict)
    frozen_records: List[ScheduleRecord] = field(default_factory=list)
    arrival_stream_index: Dict[float, List[int]] = field(default_factory=dict)
    last_reschedule_time: float = -1.0
    current_plan: Dict[str, object] = field(default_factory=dict)

