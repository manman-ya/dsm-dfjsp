from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, cast

import matplotlib.pyplot as plt
import yaml

from smdfjsp.core.types import Job, RollingConfig, SMDFJSPInstance, ScheduleRecord
from smdfjsp.data.io import load_instance_json
from smdfjsp.eda_ts import EDATS, EDATSConfig
from smdfjsp.model.evaluator import evaluate_individual
from smdfjsp.model.feasibility import assert_schedule_feasible
from smdfjsp.rolling import (
    RollingScheduler,
    SelectionStrategy,
    assert_dynamic_stitching,
    solve_rescheduling_subproblem_with_edats,
)


METHOD_ORACLE = "static_full_information_oracle"
METHOD_STATIC_BASELINE = "static_no_reschedule_baseline"
METHOD_DYNAMIC = "dynamic_rolling_edats"


def _render_bar(done: int, total: int, width: int = 36) -> str:
    if total <= 0:
        return "[" + "-" * width + "] 0/0"
    ratio = max(0.0, min(1.0, done / total))
    fill = int(round(width * ratio))
    return f"[{'#' * fill}{'-' * (width - fill)}] {done}/{total} ({ratio * 100:5.1f}%)"


def _clone_instance_with_release(instance: SMDFJSPInstance, release_time_value: float) -> SMDFJSPInstance:
    jobs: List[Job] = [
        Job(
            job_id=j.job_id,
            type_id=j.type_id,
            operations=list(j.operations),
            release_time=float(release_time_value),
        )
        for j in instance.jobs
    ]
    return SMDFJSPInstance(
        name=f"{instance.name}_all_known_t0",
        num_types=instance.num_types,
        jobs=jobs,
        srus=list(instance.srus),
        transport_time=dict(instance.transport_time),
        transport_cost_per_time=dict(instance.transport_cost_per_time),
        metadata={**instance.metadata, "static_full_information_oracle": True},
        initial_jobs=[j.job_id for j in jobs],
        arrival_stream=[],
    )


def _build_subset_instance(instance: SMDFJSPInstance, job_ids: Sequence[int], name_suffix: str) -> SMDFJSPInstance:
    wanted = set(int(x) for x in job_ids)
    jobs = [
        Job(job_id=j.job_id, type_id=j.type_id, operations=list(j.operations), release_time=0.0)
        for j in instance.jobs
        if j.job_id in wanted
    ]
    t_time = {(j, s): v for (j, s), v in instance.transport_time.items() if j in wanted}
    t_cost = {(j, s): v for (j, s), v in instance.transport_cost_per_time.items() if j in wanted}
    return SMDFJSPInstance(
        name=f"{instance.name}_{name_suffix}",
        num_types=instance.num_types,
        jobs=list(jobs),
        srus=list(instance.srus),
        transport_time=t_time,
        transport_cost_per_time=t_cost,
        metadata={**instance.metadata, "subset_job_ids": sorted(wanted)},
        initial_jobs=sorted(wanted),
        arrival_stream=[],
    )


def _pick_best_solution_records(instance: SMDFJSPInstance, cfg: EDATSConfig) -> Tuple[List[ScheduleRecord], Dict[int, int]]:
    algo = EDATS(instance, cfg)
    rr = algo.run()
    candidates = [x for x in rr.nd_solutions if x.objectives is not None]
    if not candidates:
        return [], {}
    best = min(candidates, key=lambda s: (s.objectives[0], s.objectives[1]))  # type: ignore[index]
    ev = evaluate_individual(instance, best)
    return ev.records, dict(best.ua)


def _compatible_srus_for_job(job: Job, instance: SMDFJSPInstance) -> List[int]:
    out: List[int] = []
    type_srus = [s.sru_id for s in instance.srus if s.type_id == job.type_id]
    for sid in type_srus:
        ok = True
        for op in job.operations:
            if not any(opt.sru_id == sid for opt in op.options):
                ok = False
                break
        if ok:
            out.append(sid)
    if out:
        return out
    return type_srus


def _build_option_lookup(instance: SMDFJSPInstance) -> Dict[Tuple[int, int, int, int], Tuple[int, int]]:
    lookup: Dict[Tuple[int, int, int, int], Tuple[int, int]] = {}
    for job in instance.jobs:
        for op in job.operations:
            for opt in op.options:
                lookup[(job.job_id, op.op_id, opt.sru_id, opt.machine_id)] = (
                    int(opt.process_time),
                    int(opt.process_cost_per_time),
                )
    return lookup


def _summary_from_records(
    instance: SMDFJSPInstance,
    records: List[ScheduleRecord],
    assignment_by_job: Dict[int, int],
    method: str,
    seed: int,
    reschedule_count: int,
    runtime_seconds: float,
) -> Dict[str, object]:
    option_lookup = _build_option_lookup(instance)
    release_by_job = {j.job_id: float(j.release_time) for j in instance.jobs}
    process_cost = 0.0
    first_start: Dict[int, float] = {}
    proc_end: Dict[int, float] = {}
    for rec in records:
        key = (rec.job_id, rec.op_id, rec.sru_id, rec.machine_id)
        if key in option_lookup:
            pt, cp = option_lookup[key]
            process_cost += float(pt * cp)
        first_start[rec.job_id] = min(first_start.get(rec.job_id, float("inf")), float(rec.start))
        proc_end[rec.job_id] = max(proc_end.get(rec.job_id, 0.0), float(rec.end))

    transport_cost = 0.0
    completion_with_transport: Dict[int, float] = {}
    valid_jobs = []
    for job in instance.jobs:
        job_id = job.job_id
        if job_id not in first_start or job_id not in proc_end:
            continue
        sid = assignment_by_job.get(job_id)
        if sid is None:
            sid = next((r.sru_id for r in records if r.job_id == job_id), None)
        if sid is None:
            continue
        t = instance.transport_time.get((job_id, sid))
        ct = instance.transport_cost_per_time.get((job_id, sid))
        if t is None or ct is None:
            continue
        transport_cost += float(t * ct)
        completion_with_transport[job_id] = float(proc_end[job_id] + t)
        valid_jobs.append(job_id)

    total_cost = process_cost + transport_cost
    makespan = max(completion_with_transport.values()) if completion_with_transport else float("inf")
    is_complete = len(valid_jobs) == len(instance.jobs)
    if valid_jobs:
        response = sum(first_start[j] - release_by_job[j] for j in valid_jobs)
        flow = sum(
            completion_with_transport[j] - release_by_job[j]
            for j in valid_jobs
        )
        avg_response_time = response / len(valid_jobs)
        avg_flow_time = flow / len(valid_jobs)
    else:
        avg_response_time = float("inf")
        avg_flow_time = float("inf")

    if not is_complete:
        # Keep comparison fair: incomplete schedules are treated as invalid for headline metrics.
        total_cost = float("inf")
        makespan = float("inf")
        avg_response_time = float("inf")
        avg_flow_time = float("inf")

    return {
        "instance_name": instance.name,
        "seed": seed,
        "method": method,
        "total_cost": float(total_cost),
        "makespan": float(makespan),
        "avg_response_time": float(avg_response_time),
        "avg_flow_time": float(avg_flow_time),
        "reschedule_count": int(reschedule_count),
        "runtime_seconds": float(runtime_seconds),
        "scheduled_jobs": len(valid_jobs),
        "total_jobs": len(instance.jobs),
        "is_complete": bool(is_complete),
    }


def _fmt_metric(x: object, digits: int = 3) -> str:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(x)
    if not math.isfinite(v):
        return "inf"
    return f"{v:.{digits}f}"


def _build_gantt_metrics_lines(records: List[ScheduleRecord], summary: Dict[str, object]) -> List[str]:
    lines = [
        f"ops={len(records)}",
        f"jobs={len({r.job_id for r in records})}",
        f"lanes={len({(r.sru_id, r.machine_id) for r in records})}",
    ]
    lines.extend(
        [
            f"makespan={_fmt_metric(summary.get('makespan'))}",
            f"total_cost={_fmt_metric(summary.get('total_cost'))}",
            f"avg_response={_fmt_metric(summary.get('avg_response_time'))}",
            f"avg_flow={_fmt_metric(summary.get('avg_flow_time'))}",
            f"reschedules={int(summary.get('reschedule_count', 0))}",
            f"runtime_s={_fmt_metric(summary.get('runtime_seconds'))}",
            f"completeness={int(summary.get('scheduled_jobs', 0))}/{int(summary.get('total_jobs', 0))}",
            f"is_complete={bool(summary.get('is_complete', False))}",
        ]
    )
    return lines


def _plot_gantt(
    records: List[ScheduleRecord],
    title: str,
    out_path: Path,
    summary: Dict[str, object],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_lines = _build_gantt_metrics_lines(records, summary)
    lanes = sorted({(r.sru_id, r.machine_id) for r in records}, key=lambda x: (x[0], x[1]))
    if not lanes:
        fig, ax = plt.subplots(figsize=(8, 4), dpi=140)
        ax.set_title(title + " (no records)")
        ax.text(
            0.03,
            0.95,
            "\n".join(metrics_lines),
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=8,
            bbox={"facecolor": "#f5f5f5", "edgecolor": "#999999", "boxstyle": "round,pad=0.35"},
        )
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(out_path)
        plt.close(fig)
        return
    lane_pos = {lane: i for i, lane in enumerate(lanes)}
    cmap = plt.get_cmap("tab20")
    job_ids = sorted({r.job_id for r in records})
    color_map = {jid: cmap(i % 20) for i, jid in enumerate(job_ids)}
    fig_h = max(4.5, 0.45 * len(lanes) + 2.0)
    fig, ax = plt.subplots(figsize=(12.5, fig_h), dpi=150)
    for r in records:
        y = lane_pos[(r.sru_id, r.machine_id)]
        ax.barh(
            y,
            r.end - r.start,
            left=r.start,
            height=0.72,
            color=color_map[r.job_id],
            edgecolor="black",
            linewidth=0.3,
            alpha=0.9,
        )
        if (r.end - r.start) >= 1.0:
            ax.text(r.start + 0.08, y, f"J{r.job_id}-O{r.op_id}", va="center", ha="left", fontsize=7)
    ax.set_yticks(range(len(lanes)))
    ax.set_yticklabels([f"SRU{s}-M{m}" for s, m in lanes])
    ax.set_xlabel("Time")
    ax.set_ylabel("SRU-Machine")
    ax.set_title(title)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.text(
        1.01,
        1.0,
        "\n".join(metrics_lines),
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=8,
        bbox={"facecolor": "#f5f5f5", "edgecolor": "#999999", "boxstyle": "round,pad=0.35"},
    )
    fig.tight_layout(rect=(0.0, 0.0, 0.84, 1.0))
    fig.savefig(out_path)
    plt.close(fig)


def _run_static_full_information_oracle(
    instance: SMDFJSPInstance,
    edats_cfg: EDATSConfig,
    seed: int,
) -> Tuple[Dict[str, object], List[ScheduleRecord]]:
    t0 = time.perf_counter()
    oracle_inst = _clone_instance_with_release(instance, release_time_value=0.0)
    recs, ua = _pick_best_solution_records(oracle_inst, edats_cfg)
    assert_schedule_feasible(
        instance=oracle_inst,
        records=recs,
        require_complete=True,
        context=METHOD_ORACLE,
    )
    rt = time.perf_counter() - t0
    summary = _summary_from_records(
        instance=oracle_inst,
        records=recs,
        assignment_by_job=ua,
        method=METHOD_ORACLE,
        seed=seed,
        reschedule_count=0,
        runtime_seconds=rt,
    )
    summary["instance_name"] = instance.name
    return summary, recs


def _run_static_no_reschedule_baseline(
    instance: SMDFJSPInstance,
    edats_cfg: EDATSConfig,
    seed: int,
) -> Tuple[Dict[str, object], List[ScheduleRecord]]:
    """
    Static baseline assumption:
    - Only schedule initial jobs once at t=0 with full optimization.
    - Later-arriving jobs are appended by deterministic earliest-feasible rule.
    - No global re-optimization after t=0.
    """
    t0 = time.perf_counter()
    initial_ids = sorted(instance.initial_jobs) if instance.initial_jobs else sorted(j.job_id for j in instance.jobs if j.release_time <= 0.0)
    future_jobs = sorted([j for j in instance.jobs if j.job_id not in set(initial_ids)], key=lambda x: (x.release_time, x.job_id))
    initial_inst = _build_subset_instance(instance, initial_ids, name_suffix="initial_t0")
    recs, ua = _pick_best_solution_records(initial_inst, edats_cfg)
    all_records = list(recs)
    assignment_by_job = dict(ua)

    machine_ready: Dict[Tuple[int, int], float] = {}
    job_ready: Dict[int, float] = {}
    for rec in all_records:
        machine_ready[(rec.sru_id, rec.machine_id)] = max(machine_ready.get((rec.sru_id, rec.machine_id), 0.0), rec.end)
        job_ready[rec.job_id] = max(job_ready.get(rec.job_id, 0.0), rec.end)

    for job in future_jobs:
        candidates = _compatible_srus_for_job(job, instance)
        if not candidates:
            continue
        chosen_sru = min(candidates, key=lambda sid: instance.transport_time.get((job.job_id, sid), 10**9))
        assignment_by_job[job.job_id] = chosen_sru
        cur = max(float(job.release_time), float(job_ready.get(job.job_id, job.release_time)))
        for op in job.operations:
            options = [opt for opt in op.options if opt.sru_id == chosen_sru]
            if not options:
                # If chosen SRU turns invalid unexpectedly, fallback to all options of this operation.
                options = list(op.options)
                if not options:
                    continue
                chosen_sru = options[0].sru_id
                assignment_by_job[job.job_id] = chosen_sru
                options = [opt for opt in op.options if opt.sru_id == chosen_sru]
            best_opt = None
            best_st = 0.0
            best_en = float("inf")
            for opt in options:
                st = max(cur, float(machine_ready.get((opt.sru_id, opt.machine_id), 0.0)), float(job.release_time))
                en = st + float(opt.process_time)
                if en < best_en or (en == best_en and (best_opt is None or opt.machine_id < best_opt.machine_id)):
                    best_opt = opt
                    best_st = st
                    best_en = en
            if best_opt is None:
                continue
            all_records.append(
                ScheduleRecord(
                    job_id=job.job_id,
                    op_id=op.op_id,
                    sru_id=best_opt.sru_id,
                    machine_id=best_opt.machine_id,
                    start=best_st,
                    end=best_en,
                )
            )
            machine_ready[(best_opt.sru_id, best_opt.machine_id)] = best_en
            cur = best_en
        job_ready[job.job_id] = cur

    assert_schedule_feasible(
        instance=instance,
        records=all_records,
        require_complete=True,
        context=METHOD_STATIC_BASELINE,
    )
    rt = time.perf_counter() - t0
    summary = _summary_from_records(
        instance=instance,
        records=all_records,
        assignment_by_job=assignment_by_job,
        method=METHOD_STATIC_BASELINE,
        seed=seed,
        reschedule_count=0,
        runtime_seconds=rt,
    )
    return summary, all_records


def _estimate_until_time(instance: SMDFJSPInstance) -> float:
    max_release = max((float(j.release_time) for j in instance.jobs), default=0.0)
    proc_lb = 0.0
    for j in instance.jobs:
        for op in j.operations:
            if op.options:
                proc_lb += min(float(x.process_time) for x in op.options)
    max_t = max(instance.transport_time.values()) if instance.transport_time else 0
    return max_release + proc_lb + float(max_t) * 2.0 + 10.0


def apply_reschedule_policy(
    rolling_cfg: RollingConfig,
    policy: str,
    interval: float | None = None,
) -> RollingConfig:
    out = RollingConfig(
        trigger_on_arrival=rolling_cfg.trigger_on_arrival,
        trigger_on_periodic=rolling_cfg.trigger_on_periodic,
        periodic_interval=rolling_cfg.periodic_interval,
        trigger_on_machine_idle=rolling_cfg.trigger_on_machine_idle,
        trigger_on_op_finish=rolling_cfg.trigger_on_op_finish,
        reschedule_cooldown=rolling_cfg.reschedule_cooldown,
    )
    p = str(policy).strip().lower()
    if p == "arrival":
        out.trigger_on_arrival = True
        out.trigger_on_periodic = False
    elif p == "periodic":
        out.trigger_on_arrival = False
        out.trigger_on_periodic = True
    elif p == "hybrid":
        out.trigger_on_arrival = True
        out.trigger_on_periodic = True
    else:
        raise ValueError(f"Unsupported reschedule policy: {policy}")
    if interval is not None:
        out.periodic_interval = float(interval)
    return out


def _run_dynamic_rolling_edats(
    instance: SMDFJSPInstance,
    edats_cfg: EDATSConfig,
    rolling_cfg: RollingConfig,
    seed: int,
    until_time: float,
    selection_strategy: SelectionStrategy = "cost_then_makespan",
    selection_cycle: int = 1,
    show_progress: bool = True,
) -> Tuple[Dict[str, object], List[ScheduleRecord], Dict[str, object]]:
    t0 = time.perf_counter()
    callback_round = 0
    callback_runtime_s = 0.0
    selection_trace: List[Dict[str, object]] = []

    # Approximate upper bound for replan opportunities.
    scheduler_preview = RollingScheduler(instance=instance, callback=lambda *_: [], cfg=rolling_cfg, start_time=0.0)
    planned_triggers = len(scheduler_preview._build_trigger_times(until_time=float(until_time)))  # noqa: SLF001

    def callback(full_instance: SMDFJSPInstance, state) -> List[ScheduleRecord]:
        nonlocal callback_round, callback_runtime_s
        callback_round += 1
        if show_progress:
            print(
                "[dynamic] "
                + _render_bar(min(callback_round, planned_triggers), planned_triggers)
                + f" reschedules={callback_round}"
            )
        solve_seed = int(seed + callback_round * 7919)
        solved = solve_rescheduling_subproblem_with_edats(
            instance=full_instance,
            state=state,
            config=edats_cfg,
            selection_strategy=selection_strategy,
            selection_cycle=selection_cycle,
            round_index=callback_round - 1,
            seed=solve_seed,
        )
        callback_runtime_s += float(solved.runtime_s)
        trace_row: Dict[str, object] = {
            "round": callback_round,
            "time": float(state.current_time),
            "subproblem": solved.subproblem_name,
            "nd_size": len(solved.nd_solutions),
            "candidate_size": len(solved.candidates),
            "selected_index": solved.selected_index,
            "selection_strategy": solved.selection_strategy,
        }
        if solved.selected is None:
            selection_trace.append(trace_row)
            return []
        selected_obj = solved.selected.solution.objectives
        if selected_obj is not None:
            trace_row["selected_cost"] = float(selected_obj[0])
            trace_row["selected_makespan"] = float(selected_obj[1])
        selection_trace.append(trace_row)
        assert_dynamic_stitching(
            instance=full_instance,
            state=state,
            candidate_records=solved.selected.lifted_records,
            trigger_time=float(state.current_time),
            context=f"{METHOD_DYNAMIC}:t{state.current_time:.6f}",
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
        context=METHOD_DYNAMIC,
    )
    assignment_by_job = dict(state.frozen_ua_by_job)
    for rec in final_records:
        assignment_by_job.setdefault(rec.job_id, rec.sru_id)

    rt = time.perf_counter() - t0
    summary = _summary_from_records(
        instance=instance,
        records=final_records,
        assignment_by_job=assignment_by_job,
        method=METHOD_DYNAMIC,
        seed=seed,
        reschedule_count=int(state.reschedule_count),
        runtime_seconds=rt,
    )
    details = {
        "runtime_callback_seconds": float(callback_runtime_s),
        "reschedule_count": int(state.reschedule_count),
        "selection_trace": selection_trace,
        "event_log": list(state.event_log),
        "completed_jobs": sorted(state.completed_jobs),
        "future_jobs": sorted(state.future_jobs),
        "active_jobs": sorted(state.active_jobs),
    }
    return summary, final_records, details


def _load_cfg(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_rows_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Static vs Dynamic fair comparison experiment for SM-DFJSP.")
    parser.add_argument("--config", default="configs/static_vs_dynamic.yaml")
    parser.add_argument("--instance", default=None, help="Path relative to repo root, overrides config.instance")
    parser.add_argument("--seed", type=int, default=None, help="Override random seed")
    parser.add_argument("--rolling-interval", type=float, default=None, help="Override rolling periodic interval")
    parser.add_argument(
        "--reschedule-policy",
        default=None,
        choices=["arrival", "periodic", "hybrid"],
        help="Rescheduling trigger policy.",
    )
    parser.add_argument(
        "--selection-strategy",
        default=None,
        choices=["cost_then_makespan", "min_makespan", "knee", "random"],
        help="Representative solution strategy in each ND set.",
    )
    parser.add_argument("--selection-cycle", type=int, default=None, help="Cycle index for deterministic strategy rotation.")
    parser.add_argument("--dynamic-enabled", action="store_true", help="Enable dynamic rolling method")
    parser.add_argument("--disable-dynamic", action="store_true", help="Disable dynamic rolling method")
    parser.add_argument(
        "--only-oracle",
        action="store_true",
        help=f"Run only {METHOD_ORACLE} and skip other methods.",
    )
    parser.add_argument("--out-dir", default=None, help="Override output directory")
    parser.add_argument("--until-time", type=float, default=None, help="Override rolling horizon")
    parser.add_argument("--no-progress", action="store_true", help="Disable progress bars")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = _load_cfg(root / args.config)
    instance_path = root / (args.instance or cfg["instance"])
    out_dir = root / (args.out_dir or cfg.get("out_dir", "reports/static_vs_dynamic"))
    out_dir.mkdir(parents=True, exist_ok=True)

    seed = int(args.seed if args.seed is not None else cfg.get("seed", 20260408))
    instance = load_instance_json(instance_path)

    edats_cfg_dict = dict(cfg["eda_ts"])
    edats_cfg_dict["seed"] = seed
    edats_cfg = EDATSConfig(**edats_cfg_dict)

    rolling_base = RollingConfig(**dict(cfg.get("rolling", {})))
    policy = str(args.reschedule_policy or cfg.get("reschedule_policy", "hybrid"))
    interval_override = args.rolling_interval if args.rolling_interval is not None else cfg.get("reschedule_interval")
    if interval_override is None:
        interval_override = rolling_base.periodic_interval
    rolling_cfg = apply_reschedule_policy(rolling_base, policy=policy, interval=float(interval_override))
    selection_strategy = cast(
        SelectionStrategy,
        str(args.selection_strategy or cfg.get("selection_strategy", "cost_then_makespan")),
    )
    selection_cycle = int(args.selection_cycle if args.selection_cycle is not None else cfg.get("selection_cycle", 1))

    dynamic_enabled = bool(cfg.get("dynamic_enabled", True))
    if args.dynamic_enabled:
        dynamic_enabled = True
    if args.disable_dynamic:
        dynamic_enabled = False

    until_time = float(args.until_time if args.until_time is not None else cfg.get("until_time", _estimate_until_time(instance)))

    rows: List[Dict[str, object]] = []
    records_by_method: Dict[str, List[ScheduleRecord]] = {}
    details_by_method: Dict[str, Dict[str, object]] = {}
    total_methods = 1 + (0 if args.only_oracle else 1) + (0 if args.only_oracle or not dynamic_enabled else 1)
    done_methods = 0
    if not args.no_progress:
        print("Overall Progress " + _render_bar(done_methods, total_methods))

    row_o, rec_o = _run_static_full_information_oracle(instance, edats_cfg, seed)
    rows.append(row_o)
    records_by_method[METHOD_ORACLE] = rec_o
    done_methods += 1
    if not args.no_progress:
        print("Overall Progress " + _render_bar(done_methods, total_methods))

    if not args.only_oracle:
        row_b, rec_b = _run_static_no_reschedule_baseline(instance, edats_cfg, seed)
        rows.append(row_b)
        records_by_method[METHOD_STATIC_BASELINE] = rec_b
        done_methods += 1
        if not args.no_progress:
            print("Overall Progress " + _render_bar(done_methods, total_methods))

        if dynamic_enabled:
            row_d, rec_d, details_d = _run_dynamic_rolling_edats(
                instance,
                edats_cfg,
                rolling_cfg,
                seed,
                until_time=until_time,
                selection_strategy=selection_strategy,
                selection_cycle=selection_cycle,
                show_progress=not args.no_progress,
            )
            rows.append(row_d)
            records_by_method[METHOD_DYNAMIC] = rec_d
            details_by_method[METHOD_DYNAMIC] = details_d
            done_methods += 1
            if not args.no_progress:
                print("Overall Progress " + _render_bar(done_methods, total_methods))

    results_csv = out_dir / "metrics_static_vs_dynamic.csv"
    results_json = out_dir / "metrics_static_vs_dynamic.json"
    _write_rows_csv(results_csv, rows)
    results_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    gantt_dir = out_dir / "gantt"
    summary_by_method = {str(r["method"]): r for r in rows}
    for method, recs in records_by_method.items():
        _plot_gantt(
            recs,
            title=f"{instance.name} | {method}",
            out_path=gantt_dir / f"gantt_{instance.name}_{method}.png",
            summary=summary_by_method[method],
        )
        # Save raw records for reproducibility.
        payload = [
            {
                "job_id": r.job_id,
                "op_id": r.op_id,
                "sru_id": r.sru_id,
                "machine_id": r.machine_id,
                "start": r.start,
                "end": r.end,
            }
            for r in recs
        ]
        (out_dir / f"schedule_{instance.name}_{method}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    for method, payload in details_by_method.items():
        (out_dir / f"details_{instance.name}_{method}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"instance={instance.name}")
    print(f"seed={seed}")
    print(f"results_csv={results_csv.as_posix()}")
    for r in rows:
        print(
            f"{r['method']}: total_cost={r['total_cost']:.3f}, makespan={r['makespan']:.3f}, "
            f"avg_response={r['avg_response_time']:.3f}, avg_flow={r['avg_flow_time']:.3f}, "
            f"reschedule_count={r['reschedule_count']}, runtime={r['runtime_seconds']:.3f}s"
        )


if __name__ == "__main__":
    main()
