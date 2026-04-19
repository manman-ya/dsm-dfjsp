from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Dict, List

import yaml

from smdfjsp.core.types import RollingConfig
from smdfjsp.data.io import load_instance_json
from smdfjsp.eda_ts import EDATSConfig

from run_static_vs_dynamic_experiments import (
    METHOD_DYNAMIC,
    METHOD_ORACLE,
    METHOD_STATIC_BASELINE,
    _estimate_until_time,
    _run_dynamic_rolling_edats,
    _run_static_full_information_oracle,
    _run_static_no_reschedule_baseline,
    apply_reschedule_policy,
)


def _write_rows_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _safe_std(vals: List[float]) -> float:
    return statistics.pstdev(vals) if len(vals) > 1 else 0.0


def _build_summary(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    by_method: Dict[str, List[Dict[str, object]]] = {}
    for row in rows:
        by_method.setdefault(str(row["method"]), []).append(row)

    out: List[Dict[str, object]] = []
    for method, items in sorted(by_method.items()):
        total_cost = [float(x["total_cost"]) for x in items]
        makespan = [float(x["makespan"]) for x in items]
        avg_response = [float(x["avg_response_time"]) for x in items]
        avg_flow = [float(x["avg_flow_time"]) for x in items]
        reschedule = [float(x["reschedule_count"]) for x in items]
        runtime = [float(x["runtime"]) for x in items]
        complete_ratio = [1.0 if bool(x["is_complete"]) else 0.0 for x in items]
        out.append(
            {
                "method": method,
                "n_runs": len(items),
                "mean_total_cost": sum(total_cost) / len(total_cost),
                "std_total_cost": _safe_std(total_cost),
                "mean_makespan": sum(makespan) / len(makespan),
                "std_makespan": _safe_std(makespan),
                "mean_avg_response_time": sum(avg_response) / len(avg_response),
                "std_avg_response_time": _safe_std(avg_response),
                "mean_avg_flow_time": sum(avg_flow) / len(avg_flow),
                "std_avg_flow_time": _safe_std(avg_flow),
                "mean_reschedule_count": sum(reschedule) / len(reschedule),
                "std_reschedule_count": _safe_std(reschedule),
                "mean_runtime": sum(runtime) / len(runtime),
                "std_runtime": _safe_std(runtime),
                "completion_rate": sum(complete_ratio) / len(complete_ratio),
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Repeated static-vs-dynamic rolling EDA-TS experiments.")
    parser.add_argument("--instance", default=None, help="Path relative to repo root.")
    parser.add_argument("--config", default="configs/static_vs_dynamic.yaml")
    parser.add_argument("--n-runs", type=int, default=10)
    parser.add_argument("--base-seed", type=int, default=20260408)
    parser.add_argument("--until-time", type=float, default=None)
    parser.add_argument("--selection-cycle", type=int, default=1)
    parser.add_argument(
        "--reschedule-policy",
        default="hybrid",
        choices=["arrival", "periodic", "hybrid"],
    )
    parser.add_argument("--reschedule-interval", type=float, default=None)
    parser.add_argument(
        "--selection-strategy",
        default="cost_then_makespan",
        choices=["cost_then_makespan", "min_makespan", "knee", "random"],
    )
    parser.add_argument("--out-dir", default="reports/dynamic_multi")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))
    instance_path = root / (args.instance or cfg["instance"])
    out_dir = root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    instance = load_instance_json(instance_path)
    until_time = float(args.until_time if args.until_time is not None else cfg.get("until_time", _estimate_until_time(instance)))
    rolling_base = RollingConfig(**dict(cfg.get("rolling", {})))
    interval = args.reschedule_interval if args.reschedule_interval is not None else cfg.get("reschedule_interval")
    if interval is None:
        interval = rolling_base.periodic_interval
    rolling_cfg = apply_reschedule_policy(
        rolling_base,
        policy=args.reschedule_policy,
        interval=float(interval),
    )

    metrics_rows: List[Dict[str, object]] = []
    for run_idx in range(1, int(args.n_runs) + 1):
        seed = int(args.base_seed) + run_idx - 1
        edats_cfg = EDATSConfig(seed=seed, **dict(cfg["eda_ts"]))

        row_o, rec_o = _run_static_full_information_oracle(instance, edats_cfg, seed)
        row_b, rec_b = _run_static_no_reschedule_baseline(instance, edats_cfg, seed)
        row_d, rec_d, details_d = _run_dynamic_rolling_edats(
            instance=instance,
            edats_cfg=edats_cfg,
            rolling_cfg=rolling_cfg,
            seed=seed,
            until_time=until_time,
            selection_strategy=args.selection_strategy,
            selection_cycle=int(args.selection_cycle),
            show_progress=False,
        )
        run_rows = [row_o, row_b, row_d]
        for row in run_rows:
            row["run"] = run_idx
            row["runtime"] = float(row.get("runtime_seconds", 0.0))
            metrics_rows.append(row)

        run_details = {
            "run": run_idx,
            "seed": seed,
            "instance": instance.name,
            "until_time": until_time,
            "selection_strategy": args.selection_strategy,
            "selection_cycle": int(args.selection_cycle),
            "reschedule_policy": args.reschedule_policy,
            "reschedule_interval": float(interval),
            "methods": {
                METHOD_ORACLE: {
                    "summary": row_o,
                    "record_count": len(rec_o),
                },
                METHOD_STATIC_BASELINE: {
                    "summary": row_b,
                    "record_count": len(rec_b),
                },
                METHOD_DYNAMIC: {
                    "summary": row_d,
                    "record_count": len(rec_d),
                    "details": details_d,
                },
            },
            "validation_passed": bool(row_d.get("is_complete", False)),
            "validation_errors": [],
        }
        (out_dir / f"run_{run_idx}_details.json").write_text(
            json.dumps(run_details, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary_rows = _build_summary(metrics_rows)
    _write_rows_csv(out_dir / "metrics_dynamic.csv", metrics_rows)
    _write_rows_csv(out_dir / "summary_dynamic.csv", summary_rows)
    (out_dir / "metrics_dynamic.json").write_text(
        json.dumps(metrics_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"instance={instance.name}")
    print(f"runs={args.n_runs}")
    print(f"out_dir={out_dir.as_posix()}")
    print(f"metrics={ (out_dir / 'metrics_dynamic.csv').as_posix() }")
    print(f"summary={ (out_dir / 'summary_dynamic.csv').as_posix() }")


if __name__ == "__main__":
    main()

