from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import yaml

from smdfjsp.data.dataset_builder import convert_static_instance_to_dynamic
from smdfjsp.data.io import load_instance_json, save_instance_json


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    q = min(1.0, max(0.0, float(q)))
    pos = q * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


def _estimate_arrival_window_by_initial_progress(
    inst,
    initial_job_ids: Sequence[int],
    op_range: Tuple[int, int],
    step: int,
) -> Tuple[int, int]:
    k_low = max(1, int(op_range[0]))
    k_high = max(k_low, int(op_range[1]))
    job_map = {j.job_id: j for j in inst.jobs}
    t_low_vals: List[float] = []
    t_high_vals: List[float] = []
    for jid in initial_job_ids:
        job = job_map.get(jid)
        if job is None or not job.operations:
            continue
        cum = 0.0
        prefix: List[float] = []
        for op in job.operations:
            best_pt = min(float(opt.process_time) for opt in op.options)
            cum += best_pt
            prefix.append(cum)
        idx_low = min(k_low, len(prefix)) - 1
        idx_high = min(k_high, len(prefix)) - 1
        t_low_vals.append(prefix[idx_low])
        t_high_vals.append(prefix[idx_high])

    if not t_low_vals or not t_high_vals:
        return step * 8, step * 24

    # Use robust quantiles to avoid too-early clustering and too-late tail.
    t_low = int(round(_quantile(t_low_vals, 0.45)))
    t_high = int(round(_quantile(t_high_vals, 0.70)))
    t_low = max(step, (t_low // step) * step)
    t_high = max(t_low + step, (t_high // step) * step)
    return t_low, t_high


def _assign_future_release_times(
    future_job_ids: Sequence[int],
    low_t: int,
    high_t: int,
    step: int,
    seed: int,
) -> Dict[int, float]:
    ids = [int(x) for x in future_job_ids]
    if not ids:
        return {}
    rng = random.Random(int(seed))
    rng.shuffle(ids)
    n = len(ids)
    low_t = int(low_t)
    high_t = int(max(low_t, high_t))
    step = max(1, int(step))

    if n == 1:
        bases = [0.5 * (low_t + high_t)]
    else:
        span = float(high_t - low_t)
        bases = [low_t + (span * i / (n - 1)) for i in range(n)]
    jitter = max(float(step), float(high_t - low_t) / max(8.0, 2.0 * n))

    rel: Dict[int, float] = {}
    for jid, base in zip(ids, bases):
        t = base + rng.uniform(-jitter, jitter)
        t = min(float(high_t), max(float(low_t), t))
        t_snap = int(round(t / step) * step)
        rel[jid] = float(max(step, t_snap))
    return rel


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate dauzere dynamic instances with later arrivals: "
            "future jobs enter after initial jobs are estimated to finish op 3~6."
        )
    )
    parser.add_argument("--config", default="configs/dynamic_dauzere_late36.yaml")
    parser.add_argument("--source-dir", default=None, help="Override source directory.")
    parser.add_argument("--output-dir", default=None, help="Override output directory.")
    parser.add_argument("--manifest-name", default=None, help="Override manifest filename.")
    parser.add_argument("--pattern", default=None, help="Glob pattern for source files.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))

    source_dir = root / (args.source_dir or cfg.get("source_dir", "data/dauzere_dynamic"))
    output_dir = root / (args.output_dir or cfg.get("output_dir", "data/dauzere_dynamic_late36_batch"))
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / (args.manifest_name or cfg.get("manifest_name", "manifest_dynamic_late36.csv"))

    pattern = str(args.pattern or cfg.get("pattern", "sdmk*_dyn.json"))
    seed = int(cfg.get("seed", 20260418))
    step = int(cfg.get("release_time_step", 5))
    op_range = tuple(cfg.get("initial_progress_ops_range", [3, 6]))
    name_suffix = str(cfg.get("name_suffix", "_late36"))
    window_scale = float(cfg.get("arrival_window_scale", 1.2))
    min_shift_steps = int(cfg.get("min_shift_steps", 3))

    source_files = sorted(source_dir.glob(pattern))
    if not source_files:
        raise FileNotFoundError(f"No source json matched '{pattern}' under {source_dir}")

    rows: List[Dict[str, object]] = []
    for idx, src in enumerate(source_files):
        inst = load_instance_json(src)
        initial_jobs = sorted(inst.initial_jobs) if inst.initial_jobs else sorted(j.job_id for j in inst.jobs if j.release_time <= 0.0)
        initial_set = set(initial_jobs)
        future_jobs = [j.job_id for j in inst.jobs if j.job_id not in initial_set]
        base_low, base_high = _estimate_arrival_window_by_initial_progress(inst, initial_jobs, op_range=op_range, step=step)

        # Slightly widen and move the window later than the original earliest arrivals.
        span = max(step, base_high - base_low)
        mid = 0.5 * (base_low + base_high)
        half = 0.5 * span * max(1.0, window_scale)
        low_t = int(max(step, round(mid - half)))
        high_t = int(max(low_t + step, round(mid + half)))
        low_t = (low_t // step) * step
        high_t = (high_t // step) * step

        old_future = [int(round(j.release_time)) for j in inst.jobs if j.job_id in future_jobs and j.release_time > 0.0]
        if old_future:
            low_t = max(low_t, min(old_future) + min_shift_steps * step)
            high_t = max(high_t, low_t + step)

        rel_map: Dict[int, float] = {jid: 0.0 for jid in initial_jobs}
        rel_map.update(
            _assign_future_release_times(
                future_job_ids=future_jobs,
                low_t=low_t,
                high_t=high_t,
                step=step,
                seed=seed + idx,
            )
        )

        dyn = convert_static_instance_to_dynamic(
            instance=inst,
            release_time_by_job=rel_map,
            initial_jobs=initial_jobs,
            dynamic_tag="dauzere_dynamic_late36",
        )
        dyn.name = f"{inst.name}{name_suffix}"
        dyn.metadata["dynamic_source"] = "dauzere_dynamic_retimed"
        dyn.metadata["dynamic_seed"] = seed + idx
        dyn.metadata["initial_progress_ops_range"] = [int(op_range[0]), int(op_range[1])]
        dyn.metadata["arrival_release_window"] = [int(low_t), int(high_t)]
        dyn.metadata["arrival_window_scale"] = float(window_scale)
        dyn.metadata["release_time_step"] = int(step)
        dyn.metadata["source_instance"] = str(inst.name)

        out_file = output_dir / f"{dyn.name}.json"
        save_instance_json(dyn, out_file)

        new_future_times = [int(round(j.release_time)) for j in dyn.jobs if j.release_time > 0.0]
        rows.append(
            {
                "instance": dyn.name,
                "source": src.name,
                "jobs": len(dyn.jobs),
                "initial_jobs": len(initial_jobs),
                "future_jobs": len(future_jobs),
                "arrival_events": len(dyn.arrival_stream),
                "seed": seed + idx,
                "file": out_file.relative_to(root).as_posix(),
                "arrival_min": min(new_future_times) if new_future_times else 0,
                "arrival_max": max(new_future_times) if new_future_times else 0,
            }
        )

    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "instance",
                "source",
                "jobs",
                "initial_jobs",
                "future_jobs",
                "arrival_events",
                "seed",
                "file",
                "arrival_min",
                "arrival_max",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Retimed dynamic dataset generated: {len(rows)} instances")
    print(f"Output dir: {output_dir}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
