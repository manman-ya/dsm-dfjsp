from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from smdfjsp.analysis import (
    compute_static_reference_front,
    extract_static_representative_points,
    map_dynamic_point_to_static_front,
    plot_distance_to_front,
    plot_dynamic_gantt,
    plot_gap_to_front,
    plot_metric_bars,
    plot_pareto_front_vs_dynamic_points,
    plot_rescheduling_timeline,
    summarize_dynamic_vs_static_results,
)
from smdfjsp.core.pareto import get_non_dominated_indices
from smdfjsp.core.types import ObjPair, ScheduleRecord
from smdfjsp.data.io import load_instance_json
from smdfjsp.eda_ts import EDATSConfig
from smdfjsp.model.evaluator import evaluate_individual

from run_static_vs_dynamic_experiments import (
    METHOD_DYNAMIC,
    METHOD_ORACLE,
    METHOD_STATIC_BASELINE,
    SelectionStrategy,
    _estimate_until_time,
    _run_dynamic_rolling_edats,
    _run_static_no_reschedule_baseline,
    _summary_from_records,
    apply_reschedule_policy,
)


def _write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _merge_fronts(fronts: List[List[ObjPair]]) -> List[ObjPair]:
    merged = [x for f in fronts for x in f]
    if not merged:
        return []
    idx = get_non_dominated_indices(merged)
    out = [merged[i] for i in idx]
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def _method_label(method: str, selection_policy: str) -> str:
    if method == METHOD_DYNAMIC:
        return f"dynamic_{selection_policy}"
    return method


def _add_front_mapping(
    row: Dict[str, object],
    point: Tuple[float, float],
    static_front: List[ObjPair],
) -> Dict[str, object]:
    mapped = map_dynamic_point_to_static_front(point, static_front)
    out = dict(row)
    out.update(mapped)
    return out


def _summarize_rows(
    rows: List[Dict[str, object]],
    group_keys: Tuple[str, ...],
    metrics: List[str],
) -> List[Dict[str, object]]:
    grouped: Dict[Tuple[object, ...], List[Dict[str, object]]] = {}
    for row in rows:
        key = tuple(row.get(k) for k in group_keys)
        grouped.setdefault(key, []).append(row)
    out: List[Dict[str, object]] = []
    for key, items in sorted(grouped.items(), key=lambda x: tuple(str(v) for v in x[0])):
        row: Dict[str, object] = {group_keys[i]: key[i] for i in range(len(group_keys))}
        row["n_runs"] = len(items)
        for metric in metrics:
            vals = [float(x[metric]) for x in items]
            mean = sum(vals) / len(vals)
            if len(vals) > 1:
                var = sum((v - mean) ** 2 for v in vals) / len(vals)
                std = var ** 0.5
            else:
                std = 0.0
            row[f"mean_{metric}"] = float(mean)
            row[f"std_{metric}"] = float(std)
        out.append(row)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare dynamic rolling EDA-TS endpoints against static reference front.")
    parser.add_argument("--instance", default=None)
    parser.add_argument("--config", default="configs/static_vs_dynamic_smoke.yaml")
    parser.add_argument("--n-runs", type=int, default=2)
    parser.add_argument("--base-seed", type=int, default=20260408)
    parser.add_argument("--until-time", type=float, default=None)
    parser.add_argument("--selection-cycle", type=int, default=1)
    parser.add_argument("--reschedule-policy", default="hybrid", choices=["arrival", "periodic", "hybrid"])
    parser.add_argument("--reschedule-interval", type=float, default=None)
    parser.add_argument("--out-dir", default="reports/dynamic_vs_static_front")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))
    instance_path = root / (args.instance or cfg["instance"])
    out_dir = root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    instance = load_instance_json(instance_path)
    until_time = float(args.until_time if args.until_time is not None else cfg.get("until_time", _estimate_until_time(instance)))
    # Construct base rolling cfg from config first, then apply policy overrides.
    from smdfjsp.core.types import RollingConfig

    rolling_raw = RollingConfig(**dict(cfg.get("rolling", {})))
    interval = args.reschedule_interval if args.reschedule_interval is not None else cfg.get("reschedule_interval")
    if interval is None:
        interval = rolling_raw.periodic_interval
    rolling_cfg = apply_reschedule_policy(rolling_raw, policy=args.reschedule_policy, interval=float(interval))

    selection_policies: List[SelectionStrategy] = [
        "cost_then_makespan",
        "min_makespan",
        "knee",
        "random",
    ]

    front_rows: List[Dict[str, object]] = []
    compare_rows: List[Dict[str, object]] = []
    runtime_rows: List[Dict[str, object]] = []
    all_fronts: List[List[ObjPair]] = []
    first_run_event_logs: Dict[str, List[Dict[str, object]]] = {}
    first_run_completion: Dict[str, float] = {}
    first_run_records_by_policy: Dict[str, List[ScheduleRecord]] = {}

    for run_idx in range(1, int(args.n_runs) + 1):
        seed = int(args.base_seed) + run_idx - 1
        edats_cfg = EDATSConfig(seed=seed, **dict(cfg["eda_ts"]))
        static_ref = compute_static_reference_front(instance=instance, config=edats_cfg, seed=seed)
        static_front = list(static_ref.front_points)
        all_fronts.append(static_front)
        reps = extract_static_representative_points(static_front)

        for i, p in enumerate(static_front):
            front_rows.append(
                {
                    "instance": instance.name,
                    "run": run_idx,
                    "point_id": i,
                    "total_cost": float(p[0]),
                    "makespan": float(p[1]),
                    "is_knee": bool(reps.get("knee", -1) == i),
                    "is_min_cost": bool(reps.get("min_cost", -1) == i),
                    "is_min_makespan": bool(reps.get("min_makespan", -1) == i),
                }
            )

        # Static representative points from static reference front.
        for rep_name in ["min_cost", "min_makespan", "knee"]:
            if rep_name not in reps:
                continue
            idx = reps[rep_name]
            if idx < 0 or idx >= len(static_ref.front_solutions):
                continue
            sol = static_ref.front_solutions[idx]
            ev = evaluate_individual(static_ref.instance, sol)
            summary = _summary_from_records(
                instance=static_ref.instance,
                records=ev.records,
                assignment_by_job=dict(sol.ua),
                method=METHOD_ORACLE,
                seed=seed,
                reschedule_count=0,
                runtime_seconds=static_ref.runtime_s,
            )
            row = {
                "instance": instance.name,
                "run": run_idx,
                "method": METHOD_ORACLE,
                "selection_policy": rep_name,
                "total_cost": float(summary["total_cost"]),
                "makespan": float(summary["makespan"]),
                "avg_response_time": float(summary["avg_response_time"]),
                "avg_flow_time": float(summary["avg_flow_time"]),
                "reschedule_count": int(summary["reschedule_count"]),
                "runtime": float(summary["runtime_seconds"]),
            }
            compare_rows.append(_add_front_mapping(row, (float(row["total_cost"]), float(row["makespan"])), static_front))

        # Static no-reschedule baseline.
        row_b, _ = _run_static_no_reschedule_baseline(instance=instance, edats_cfg=edats_cfg, seed=seed)
        base_row = {
            "instance": instance.name,
            "run": run_idx,
            "method": METHOD_STATIC_BASELINE,
            "selection_policy": "none",
            "total_cost": float(row_b["total_cost"]),
            "makespan": float(row_b["makespan"]),
            "avg_response_time": float(row_b["avg_response_time"]),
            "avg_flow_time": float(row_b["avg_flow_time"]),
            "reschedule_count": int(row_b["reschedule_count"]),
            "runtime": float(row_b["runtime_seconds"]),
        }
        compare_rows.append(_add_front_mapping(base_row, (base_row["total_cost"], base_row["makespan"]), static_front))

        # Dynamic rolling EDA-TS endpoints for each selection policy.
        for policy in selection_policies:
            row_d, rec_d, details_d = _run_dynamic_rolling_edats(
                instance=instance,
                edats_cfg=edats_cfg,
                rolling_cfg=rolling_cfg,
                seed=seed,
                until_time=until_time,
                selection_strategy=policy,
                selection_cycle=max(1, int(args.selection_cycle)),
                show_progress=False,
            )
            drow = {
                "instance": instance.name,
                "run": run_idx,
                "method": METHOD_DYNAMIC,
                "selection_policy": str(policy),
                "total_cost": float(row_d["total_cost"]),
                "makespan": float(row_d["makespan"]),
                "avg_response_time": float(row_d["avg_response_time"]),
                "avg_flow_time": float(row_d["avg_flow_time"]),
                "reschedule_count": int(row_d["reschedule_count"]),
                "runtime": float(row_d["runtime_seconds"]),
            }
            compare_rows.append(_add_front_mapping(drow, (drow["total_cost"], drow["makespan"]), static_front))

            if run_idx == 1:
                first_run_event_logs[str(policy)] = list(details_d.get("event_log", []))
                first_run_completion[str(policy)] = float(row_d["makespan"])
                first_run_records_by_policy[str(policy)] = rec_d

    # Runtime table with separated method labels for plotting.
    for row in compare_rows:
        if str(row["method"]) == METHOD_ORACLE and str(row["selection_policy"]) != "knee":
            continue
        runtime_rows.append(
            {
                "instance": row["instance"],
                "run": row["run"],
                "method": row["method"],
                "selection_policy": row["selection_policy"],
                "method_label": _method_label(str(row["method"]), str(row["selection_policy"])),
                "avg_response_time": row["avg_response_time"],
                "avg_flow_time": row["avg_flow_time"],
                "reschedule_count": row["reschedule_count"],
                "runtime": row["runtime"],
            }
        )

    # Persist csv/json tables.
    _write_csv(out_dir / "dynamic_vs_static_front_metrics.csv", compare_rows)
    _write_csv(out_dir / "dynamic_runtime_metrics.csv", runtime_rows)
    _write_csv(out_dir / "static_reference_front.csv", front_rows)

    summary_compare = summarize_dynamic_vs_static_results(compare_rows)
    summary_runtime = _summarize_rows(
        runtime_rows,
        group_keys=("instance", "method", "selection_policy", "method_label"),
        metrics=["avg_response_time", "avg_flow_time", "reschedule_count", "runtime"],
    )
    _write_csv(out_dir / "dynamic_vs_static_front_summary.csv", summary_compare)
    _write_csv(out_dir / "dynamic_runtime_summary.csv", summary_runtime)
    (out_dir / "dynamic_vs_static_front_metrics.json").write_text(
        json.dumps(compare_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Visualizations.
    merged_front = _merge_fronts(all_fronts)
    dynamic_only = [x for x in compare_rows if str(x["method"]) == METHOD_DYNAMIC]
    plot_pareto_front_vs_dynamic_points(
        static_front=merged_front,
        dynamic_rows=dynamic_only,
        out_path=out_dir / "pareto_front_vs_dynamic_points.png",
        title=f"{instance.name} | static front vs dynamic endpoints",
    )
    plot_distance_to_front(
        rows=dynamic_only,
        out_path=out_dir / "distance_to_static_front.png",
        title=f"{instance.name} | distance to static front",
    )
    plot_gap_to_front(
        rows=dynamic_only,
        out_path=out_dir / "gap_to_static_front.png",
        title=f"{instance.name} | relative gap to static front",
    )

    method_order = [
        METHOD_ORACLE,
        METHOD_STATIC_BASELINE,
        "dynamic_cost_then_makespan",
        "dynamic_min_makespan",
        "dynamic_knee",
        "dynamic_random",
    ]
    for metric in ["avg_response_time", "avg_flow_time", "runtime", "reschedule_count"]:
        plot_metric_bars(
            rows=runtime_rows,
            metric=metric,
            out_path=out_dir / f"{metric}.png",
            title=f"{instance.name} | {metric}",
            method_order=method_order,
        )

    arrival_times = sorted({float(j.release_time) for j in instance.jobs if float(j.release_time) > 0.0})
    plot_rescheduling_timeline(
        arrival_times=arrival_times,
        policy_event_logs=first_run_event_logs,
        completion_times=first_run_completion,
        out_path=out_dir / "rescheduling_timeline.png",
        title=f"{instance.name} | rescheduling timeline",
    )
    for policy, recs in first_run_records_by_policy.items():
        reschedule_times = [float(x["time"]) for x in first_run_event_logs.get(policy, []) if "reschedule" in list(x.get("tags", []))]
        plot_dynamic_gantt(
            records=recs,
            reschedule_times=reschedule_times,
            arrival_times=arrival_times,
            out_path=out_dir / f"dynamic_gantt_{policy}.png",
            title=f"{instance.name} | dynamic gantt ({policy})",
            show_labels=True,
            label_min_width=60.0,
            color_by="job",
            show_arrival_lines=False,
            show_reschedule_lines=True,
            event_line_alpha=0.22,
            focus_on_active_horizon=True,
            show_frozen_hatch=True,
            split_by_sru=False,
            annotate_mode="all",
            frozen_split_time=(max(reschedule_times) if reschedule_times else None),
        )
        plot_dynamic_gantt(
            records=recs,
            reschedule_times=reschedule_times,
            arrival_times=arrival_times,
            out_path=out_dir / f"dynamic_gantt_{policy}_paper.png",
            title=f"{instance.name} | dynamic gantt paper ({policy})",
            show_labels=True,
            label_min_width=70.0,
            color_by="job",
            show_arrival_lines=False,
            show_reschedule_lines=True,
            event_line_alpha=0.18,
            focus_on_active_horizon=True,
            show_frozen_hatch=True,
            split_by_sru=False,
            annotate_mode="all",
            frozen_split_time=(max(reschedule_times) if reschedule_times else None),
        )

    print(f"instance={instance.name}")
    print(f"n_runs={args.n_runs}")
    print(f"out_dir={out_dir.as_posix()}")
    print(f"front_metrics={ (out_dir / 'dynamic_vs_static_front_metrics.csv').as_posix() }")
    print(f"runtime_metrics={ (out_dir / 'dynamic_runtime_metrics.csv').as_posix() }")
    print(f"static_front={ (out_dir / 'static_reference_front.csv').as_posix() }")


if __name__ == "__main__":
    main()
