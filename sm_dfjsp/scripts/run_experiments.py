from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from smdfjsp.baselines import HGATSConfig, NSGAIIConfig, run_eda, run_eda_vns, run_h_gats, run_nsgaii
from smdfjsp.data.io import load_instance_json
from smdfjsp.eda_ts import EDATS, EDATSConfig
from smdfjsp.metrics import build_pf_known, c_metric, gd, igd


def nd_objectives(nd_solutions) -> List[tuple]:
    objs = []
    for x in nd_solutions:
        if x.objectives is not None:
            objs.append((float(x.objectives[0]), float(x.objectives[1])))
    return objs


def _render_bar(done: int, total: int, width: int = 36) -> str:
    if total <= 0:
        return "[" + "-" * width + "] 0/0"
    ratio = max(0.0, min(1.0, done / total))
    fill = int(round(width * ratio))
    return f"[{'#' * fill}{'-' * (width - fill)}] {done}/{total} ({ratio * 100:5.1f}%)"


def _flush_csv(out_dir: Path, summary_rows: List[dict], metric_rows: List[dict]) -> None:
    with (out_dir / "front_points.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["instance", "algorithm", "cost", "makespan"])
        w.writeheader()
        w.writerows(summary_rows)
    with (out_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["instance", "algorithm", "GD", "IGD"])
        w.writeheader()
        w.writerows(metric_rows)


def _runner_bundle(inst, seed: int, cfg: dict):
    edats_cfg = EDATSConfig(seed=seed, **cfg["eda_ts"])
    eda_cfg = EDATSConfig(seed=seed, **cfg["eda"])
    eda_vns_cfg = EDATSConfig(seed=seed, **cfg["eda_vns"])
    nsgaii_cfg = NSGAIIConfig(seed=seed, **cfg["nsgaii"])
    h_gats_cfg = HGATSConfig(seed=seed, **cfg["h_gats"])
    return [
        ("EDA-TS", lambda: EDATS(inst, edats_cfg).run()),
        ("EDA", lambda: run_eda(inst, eda_cfg)),
        ("NSGA-II", lambda: run_nsgaii(inst, nsgaii_cfg)),
        ("EDA-VNS", lambda: run_eda_vns(inst, eda_vns_cfg)),
        ("H-GA-TS", lambda: run_h_gats(inst, h_gats_cfg)),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/experiment.yaml")
    parser.add_argument("--out-dir", default="reports")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))
    out_dir = root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    metric_rows = []
    instances = list(cfg["instances"])
    algo_order = ["EDA-TS", "EDA", "NSGA-II", "EDA-VNS", "H-GA-TS"]
    total_steps = len(instances) * len(algo_order)
    done_steps = 0

    if not args.no_progress:
        print("Overall Progress " + _render_bar(done_steps, total_steps))

    exp_start = time.time()
    for inst_idx, inst_name in enumerate(instances, start=1):
        print(f"\n=== Instance {inst_name} ({inst_idx}/{len(instances)}) ===")
        inst = load_instance_json(root / "data" / "sdmk01-15" / f"{inst_name}.json")
        seed = int(cfg["seed"])
        runners = _runner_bundle(inst, seed, cfg)
        res: Dict[str, List[tuple]] = {}

        for algo_name, algo_fn in runners:
            t0 = time.time()
            print(f"[{inst_name}] start {algo_name} ...")
            run_result = algo_fn()
            front = nd_objectives(run_result.nd_solutions)
            res[algo_name] = front
            elapsed = time.time() - t0
            if front:
                best_cost = min(x[0] for x in front)
                best_mk = min(x[1] for x in front)
                print(
                    f"[{inst_name}] done  {algo_name:8s} | nd={len(front):3d} | "
                    f"bestC={best_cost:.3f} | bestMK={best_mk:.3f} | {elapsed:.1f}s"
                )
            else:
                print(f"[{inst_name}] done  {algo_name:8s} | nd=  0 | bestC=NA | bestMK=NA | {elapsed:.1f}s")

            done_steps += 1
            if not args.no_progress:
                print("Overall Progress " + _render_bar(done_steps, total_steps))

        pf_true = build_pf_known(list(res.values()))
        for algo, front in res.items():
            for c, mk in front:
                summary_rows.append({"instance": inst_name, "algorithm": algo, "cost": c, "makespan": mk})
            metric_rows.append(
                {
                    "instance": inst_name,
                    "algorithm": algo,
                    "GD": gd(front, pf_true),
                    "IGD": igd(front, pf_true),
                }
            )
        algos = list(res.keys())
        for i in range(len(algos)):
            for j in range(i + 1, len(algos)):
                a, b = algos[i], algos[j]
                metric_rows.append(
                    {
                        "instance": inst_name,
                        "algorithm": f"C({a},{b})",
                        "GD": c_metric(res[a], res[b]),
                        "IGD": c_metric(res[b], res[a]),
                    }
                )
        _flush_csv(out_dir, summary_rows, metric_rows)
        print(f"[{inst_name}] partial csv saved: {out_dir}")
    total_elapsed = time.time() - exp_start
    print(f"\ndone. outputs in {out_dir}")
    print(f"total elapsed: {total_elapsed / 60.0:.2f} min")


if __name__ == "__main__":
    main()
