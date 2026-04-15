from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Tuple

from smdfjsp.core.types import Job, Operation, ProcessOption, SMDFJSPInstance, SRU


def save_instance_json(instance: SMDFJSPInstance, output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": instance.name,
        "num_types": instance.num_types,
        "metadata": instance.metadata,
        "jobs": [
            {
                "job_id": j.job_id,
                "type_id": j.type_id,
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
        jobs.append(Job(job_id=int(j["job_id"]), type_id=int(j["type_id"]), operations=ops))
    srus = [
        SRU(sru_id=int(s["sru_id"]), type_id=int(s["type_id"]), machine_ids=[int(x) for x in s["machine_ids"]])
        for s in data["srus"]
    ]
    t_time = {(int(x["job_id"]), int(x["sru_id"])): int(x["value"]) for x in data["transport_time"]}
    t_cost = {
        (int(x["job_id"]), int(x["sru_id"])): int(x["value"]) for x in data["transport_cost_per_time"]
    }
    return SMDFJSPInstance(
        name=data["name"],
        num_types=int(data["num_types"]),
        jobs=jobs,
        srus=srus,
        transport_time=t_time,
        transport_cost_per_time=t_cost,
        metadata=data.get("metadata", {}),
    )

