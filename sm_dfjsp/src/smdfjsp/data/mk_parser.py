from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class MKOperation:
    options: List[Tuple[int, int]]  # (global_machine_id_1based, process_time)


@dataclass
class MKJob:
    job_id: int
    operations: List[MKOperation]


@dataclass
class MKInstance:
    name: str
    num_jobs: int
    num_machines: int
    jobs: List[MKJob]


def parse_mk_file(path: str | Path) -> MKInstance:
    path = Path(path)
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    head = [int(x) for x in lines[0].split()]
    num_jobs, num_machines = head[0], head[1]
    jobs: List[MKJob] = []
    for j_idx in range(num_jobs):
        tokens = [int(x) for x in lines[j_idx + 1].split()]
        cursor = 0
        op_count = tokens[cursor]
        cursor += 1
        operations: List[MKOperation] = []
        for _ in range(op_count):
            option_count = tokens[cursor]
            cursor += 1
            options: List[Tuple[int, int]] = []
            for _ in range(option_count):
                machine_zero_based = tokens[cursor]
                process_time = tokens[cursor + 1]
                cursor += 2
                options.append((machine_zero_based + 1, process_time))
            operations.append(MKOperation(options=options))
        jobs.append(MKJob(job_id=j_idx + 1, operations=operations))
    return MKInstance(
        name=path.stem.lower(),
        num_jobs=num_jobs,
        num_machines=num_machines,
        jobs=jobs,
    )

