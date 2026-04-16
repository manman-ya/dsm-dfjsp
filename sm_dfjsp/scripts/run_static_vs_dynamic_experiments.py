from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import yaml

from smdfjsp.core.types import Job, RollingConfig, SMDFJSPInstance, ScheduleRecord
from smdfjsp.data.io import load_instance_json
from smdfjsp.eda_ts import EDATS, EDATSConfig
from smdfjsp.model.evaluator import evaluate_individual
from smdfjsp.rolling import RollingScheduler, build_remaining_subproblem, lift_records_from_subproblem


METHOD_ORACLE = "static_full_information_oracle"
METHOD_STATIC_BASELINE = "static_no_reschedule_baseline"
METHOD_DYNAMIC = "dynamic_rolling_method"


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


def _plot_gantt(records: List[ScheduleRecord], title: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lanes = sorted({(r.sru_id, r.machine_id) for r in records}, key=lambda x: (x[0], x[1]))
    if not lanes:
        fig, ax = plt.subplots(figsize=(8, 4), dpi=140)
        ax.set_title(title + " (no records)")
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
    fig.tight_layout()
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


def _run_dynamic_rolling_method(
    instance: SMDFJSPInstance,
    edats_cfg: EDATSConfig,
    rolling_cfg: RollingConfig,
    seed: int,
    until_time: float,
) -> Tuple[Dict[str, object], List[ScheduleRecord]]:
    t0 = time.perf_counter()
    reschedule_count = 0

    def callback(full_instance: SMDFJSPInstance, state) -> List[ScheduleRecord]:
        nonlocal reschedule_count
        reschedule_count += 1
        sub = build_remaining_subproblem(full_instance, state)
        if not sub.instance.jobs:
            return []
        sub_records, _ = _pick_best_solution_records(sub.instance, edats_cfg)
        return lift_records_from_subproblem(sub_records, sub.op_offset_by_job)

    scheduler = RollingScheduler(instance=instance, callback=callback, cfg=rolling_cfg, start_time=0.0)
    state = scheduler.run(until_time=until_time)
    final_records = sorted(state.frozen_records, key=lambda r: (r.start, r.end, r.job_id, r.op_id))
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
        reschedule_count=reschedule_count,
        runtime_seconds=rt,
    )
    return summary, final_records


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
    parser.add_argument("--dynamic-enabled", action="store_true", help="Enable dynamic rolling method")
    parser.add_argument("--disable-dynamic", action="store_true", help="Disable dynamic rolling method")
    parser.add_argument("--out-dir", default=None, help="Override output directory")
    parser.add_argument("--until-time", type=float, default=None, help="Override rolling horizon")
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

    rolling_dict = dict(cfg.get("rolling", {}))
    if args.rolling_interval is not None:
        rolling_dict["periodic_interval"] = float(args.rolling_interval)
    rolling_cfg = RollingConfig(**rolling_dict)

    dynamic_enabled = bool(cfg.get("dynamic_enabled", True))
    if args.dynamic_enabled:
        dynamic_enabled = True
    if args.disable_dynamic:
        dynamic_enabled = False

    until_time = float(args.until_time if args.until_time is not None else cfg.get("until_time", _estimate_until_time(instance)))

    rows: List[Dict[str, object]] = []
    records_by_method: Dict[str, List[ScheduleRecord]] = {}

    row_o, rec_o = _run_static_full_information_oracle(instance, edats_cfg, seed)
    rows.append(row_o)
    records_by_method[METHOD_ORACLE] = rec_o

    row_b, rec_b = _run_static_no_reschedule_baseline(instance, edats_cfg, seed)
    rows.append(row_b)
    records_by_method[METHOD_STATIC_BASELINE] = rec_b

    if dynamic_enabled:
        row_d, rec_d = _run_dynamic_rolling_method(instance, edats_cfg, rolling_cfg, seed, until_time=until_time)
        rows.append(row_d)
        records_by_method[METHOD_DYNAMIC] = rec_d

    results_csv = out_dir / "metrics_static_vs_dynamic.csv"
    results_json = out_dir / "metrics_static_vs_dynamic.json"
    _write_rows_csv(results_csv, rows)
    results_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    gantt_dir = out_dir / "gantt"
    for method, recs in records_by_method.items():
        _plot_gantt(
            recs,
            title=f"{instance.name} | {method}",
            out_path=gantt_dir / f"gantt_{instance.name}_{method}.png",
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
