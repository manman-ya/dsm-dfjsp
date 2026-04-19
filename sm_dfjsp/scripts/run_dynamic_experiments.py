from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from smdfjsp.core.types import RollingConfig
from smdfjsp.data.io import load_instance_json
from smdfjsp.eda_ts import EDATSConfig
from smdfjsp.model.feasibility import assert_schedule_feasible
from smdfjsp.rolling import (
    RollingScheduler,
    assert_dynamic_stitching,
    solve_rescheduling_subproblem_with_edats,
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
    selection_strategy = str(cfg.get("selection_strategy", "cost_then_makespan"))
    selection_cycle = int(cfg.get("selection_cycle", 1))
    callback_round = 0

    def callback(full_instance, state):
        nonlocal callback_round
        callback_round += 1
        solved = solve_rescheduling_subproblem_with_edats(
            instance=full_instance,
            state=state,
            config=edats_cfg,
            selection_strategy=selection_strategy,  # type: ignore[arg-type]
            selection_cycle=selection_cycle,
            round_index=callback_round - 1,
            seed=edats_cfg.seed + callback_round * 7919,
        )
        if solved.selected is None:
            return []
        assert_dynamic_stitching(
            instance=full_instance,
            state=state,
            candidate_records=solved.selected.lifted_records,
            trigger_time=float(state.current_time),
            context=f"dynamic_subproblem_t{state.current_time:.6f}",
        )
        return solved.selected.lifted_records

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
