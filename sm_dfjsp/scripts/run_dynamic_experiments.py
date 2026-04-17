from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

import yaml

from smdfjsp.core.types import DecodeContext, RollingConfig, ScheduleRecord
from smdfjsp.data.io import load_instance_json
from smdfjsp.eda_ts import EDATS, EDATSConfig
from smdfjsp.model.evaluator import evaluate_individual
from smdfjsp.model.feasibility import assert_schedule_feasible
from smdfjsp.rolling import RollingScheduler, build_remaining_subproblem, lift_records_from_subproblem


def _pick_best_records_for_subproblem(
    sub_instance,
    cfg: EDATSConfig,
    decode_ctx: DecodeContext | None = None,
) -> List[ScheduleRecord]:
    algo = EDATS(sub_instance, cfg)
    result = algo.run(eval_ctx=decode_ctx)
    if not result.nd_solutions:
        return []
    feasible = [x for x in result.nd_solutions if x.objectives is not None]
    if not feasible:
        return []
    best = min(feasible, key=lambda x: x.objectives[0] + x.objectives[1])  # type: ignore[index]
    ev = evaluate_individual(sub_instance, best, ctx=decode_ctx)
    return ev.records


def _build_subproblem_decode_context(
    sub_instance,
    machine_ready,
    job_ready,
    current_time: float,
) -> DecodeContext:
    eligible = {j.job_id for j in sub_instance.jobs}
    sub_job_ready = {j.job_id: float(job_ready.get(j.job_id, 0.0)) for j in sub_instance.jobs}
    return DecodeContext(
        current_time=float(current_time),
        eligible_job_ids=eligible,
        completed_ops_by_job={j.job_id: 0 for j in sub_instance.jobs},
        in_progress_ops={},
        frozen_job_ready=sub_job_ready,
        frozen_machine_ready=dict(machine_ready),
        frozen_records=[],
        frozen_ua_by_job={},
        include_transport_for_incomplete_jobs=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run rolling dynamic scheduling on one dynamic instance.")
    parser.add_argument("--config", default="configs/experiment_dynamic.yaml")
    parser.add_argument("--instance", default=None, help="Override instance path from config.")
    parser.add_argument("--out", default="reports/dynamic/run_summary.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))
    instance_path = root / (args.instance or cfg["instance"])
    until_time = float(cfg.get("until_time", 300.0))
    instance = load_instance_json(instance_path)
    edats_cfg_dict = dict(cfg["eda_ts"])
    edats_cfg_dict.setdefault("seed", int(cfg.get("seed", 20260408)))
    edats_cfg = EDATSConfig(**edats_cfg_dict)
    rolling_cfg = RollingConfig(**cfg["rolling"])

    def callback(full_instance, state):
        sub = build_remaining_subproblem(full_instance, state)
        if not sub.instance.jobs:
            return []
        decode_ctx = _build_subproblem_decode_context(
            sub_instance=sub.instance,
            machine_ready=state.machine_ready,
            job_ready=state.job_ready,
            current_time=state.current_time,
        )
        sub_records = _pick_best_records_for_subproblem(sub.instance, cfg=edats_cfg, decode_ctx=decode_ctx)
        assert_schedule_feasible(
            instance=sub.instance,
            records=sub_records,
            require_complete=False,
            context=f"dynamic_subproblem_t{state.current_time:.6f}",
        )
        return lift_records_from_subproblem(sub_records, sub.op_offset_by_job)

    scheduler = RollingScheduler(instance=instance, callback=callback, cfg=rolling_cfg, start_time=0.0)
    state = scheduler.run(until_time=until_time)
    final_records = sorted(state.frozen_records, key=lambda r: (r.start, r.end, r.job_id, r.op_id))
    require_complete = len(state.completed_jobs) == len(instance.jobs)
    assert_schedule_feasible(
        instance=instance,
        records=final_records,
        require_complete=require_complete,
        context="dynamic_final",
    )

    out_path = root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "instance": instance.name,
        "until_time": until_time,
        "frozen_records": len(final_records),
        "active_jobs": sorted(state.active_jobs),
        "future_jobs": sorted(state.future_jobs),
        "completed_jobs": sorted(state.completed_jobs),
        "in_progress_ops": [
            {
                "job_id": v.job_id,
                "op_id": v.op_id,
                "sru_id": v.sru_id,
                "machine_id": v.machine_id,
                "start_time": v.start_time,
                "expected_end_time": v.expected_end_time,
            }
            for v in state.in_progress_ops.values()
        ],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Dynamic run summary saved to {out_path}")


if __name__ == "__main__":
    main()
