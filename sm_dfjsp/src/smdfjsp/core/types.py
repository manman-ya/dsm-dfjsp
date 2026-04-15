from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


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

