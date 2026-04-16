from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from smdfjsp.core.types import ArrivalEvent, Job, Operation, ProcessOption, SMDFJSPInstance, SRU


def build_arrival_stream_from_release_time(jobs: List[Job]) -> List[ArrivalEvent]:
    """Build auxiliary arrival index from jobs' release_time."""
    by_time: Dict[float, List[int]] = defaultdict(list)
    for job in jobs:
        by_time[float(job.release_time)].append(int(job.job_id))
    out: List[ArrivalEvent] = []
    for t in sorted(by_time.keys()):
        out.append(ArrivalEvent(time=float(t), job_ids=sorted(by_time[t])))
    return out


def _normalize_arrival_stream(stream_raw: List[dict]) -> List[ArrivalEvent]:
    by_time: Dict[float, List[int]] = defaultdict(list)
    for row in stream_raw:
        t = float(row.get("time", 0.0))
        for job_id in row.get("job_ids", []):
            by_time[t].append(int(job_id))
    out: List[ArrivalEvent] = []
    for t in sorted(by_time.keys()):
        out.append(ArrivalEvent(time=float(t), job_ids=sorted(set(by_time[t]))))
    return out


def _arrival_stream_equal(a: List[ArrivalEvent], b: List[ArrivalEvent]) -> bool:
    if len(a) != len(b):
        return False
    for ea, eb in zip(a, b):
        if float(ea.time) != float(eb.time):
            return False
        if sorted(ea.job_ids) != sorted(eb.job_ids):
            return False
    return True


def save_instance_json(instance: SMDFJSPInstance, output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    arrival_stream = build_arrival_stream_from_release_time(instance.jobs)
    initial_jobs = sorted(
        set(instance.initial_jobs) if instance.initial_jobs else {j.job_id for j in instance.jobs if j.release_time <= 0.0}
    )
    payload = {
        "name": instance.name,
        "num_types": instance.num_types,
        "metadata": instance.metadata,
        "initial_jobs": initial_jobs,
        "jobs": [
            {
                "job_id": j.job_id,
                "type_id": j.type_id,
                "release_time": float(j.release_time),
                "operations": [
                    {
                        "op_id": op.op_id,
                        "options": [
                            {
                                "sru_id": opt.sru_id,
                                "machine_id": opt.machine_id,
                                "process_time": opt.process_time,
                                "process_cost_per_time": opt.process_cost_per_time,
                            }
                            for opt in op.options
                        ],
                    }
                    for op in j.operations
                ],
            }
            for j in instance.jobs
        ],
        "srus": [
            {"sru_id": s.sru_id, "type_id": s.type_id, "machine_ids": s.machine_ids}
            for s in instance.srus
        ],
        "transport_time": [
            {"job_id": k[0], "sru_id": k[1], "value": v} for k, v in instance.transport_time.items()
        ],
        "transport_cost_per_time": [
            {"job_id": k[0], "sru_id": k[1], "value": v}
            for k, v in instance.transport_cost_per_time.items()
        ],
        "arrival_stream": [{"time": e.time, "job_ids": e.job_ids} for e in arrival_stream],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_instance_json(path: str | Path) -> SMDFJSPInstance:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    jobs: List[Job] = []
    for j in data["jobs"]:
        ops: List[Operation] = []
        for op in j["operations"]:
            options = [
                ProcessOption(
                    sru_id=int(o["sru_id"]),
                    machine_id=int(o["machine_id"]),
                    process_time=int(o["process_time"]),
                    process_cost_per_time=int(o["process_cost_per_time"]),
                )
                for o in op["options"]
            ]
            ops.append(Operation(op_id=int(op["op_id"]), options=options))
        jobs.append(
            Job(
                job_id=int(j["job_id"]),
                type_id=int(j["type_id"]),
                operations=ops,
                release_time=float(j.get("release_time", 0.0)),
            )
        )
    srus = [
        SRU(sru_id=int(s["sru_id"]), type_id=int(s["type_id"]), machine_ids=[int(x) for x in s["machine_ids"]])
        for s in data["srus"]
    ]
    t_time = {(int(x["job_id"]), int(x["sru_id"])): int(x["value"]) for x in data["transport_time"]}
    t_cost = {
        (int(x["job_id"]), int(x["sru_id"])): int(x["value"]) for x in data["transport_cost_per_time"]
    }
    derived_stream = build_arrival_stream_from_release_time(jobs)
    loaded_stream = _normalize_arrival_stream(data.get("arrival_stream", []))
    metadata = data.get("metadata", {})
    if loaded_stream and not _arrival_stream_equal(loaded_stream, derived_stream):
        metadata = dict(metadata)
        metadata["arrival_stream_rebuilt_from_release_time"] = True
    arrival_stream = derived_stream
    initial_jobs_raw = data.get("initial_jobs", [])
    if initial_jobs_raw:
        initial_jobs = sorted({int(x) for x in initial_jobs_raw})
    else:
        initial_jobs = sorted(j.job_id for j in jobs if j.release_time <= 0.0)
    return SMDFJSPInstance(
        name=data["name"],
        num_types=int(data["num_types"]),
        jobs=jobs,
        srus=srus,
        transport_time=t_time,
        transport_cost_per_time=t_cost,
        metadata=metadata,
        initial_jobs=initial_jobs,
        arrival_stream=arrival_stream,
    )

