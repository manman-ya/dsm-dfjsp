from __future__ import annotations

import argparse
import csv
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from smdfjsp.data.io import load_instance_json
from smdfjsp.eda_ts import EDATS, EDATSConfig
from smdfjsp.metrics import build_pf_known, c_metric, gd, igd, wilcoxon_signed_rank

from repro_utils import load_yaml, write_run_meta


def to_front(res):
    return [(float(x.objectives[0]), float(x.objectives[1])) for x in res.nd_solutions if x.objectives is not None]


def _safe_std(vals: List[float]) -> float:
    return statistics.pstdev(vals) if len(vals) > 1 else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/repro/ablation_01_15_quick.yaml")
    parser.add_argument("--out-dir", default="reports/repro/ablation_01_15")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg_path = root / args.config
    cfg = load_yaml(cfg_path)
    out_dir = root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    write_run_meta(out_dir, cfg_path, extra={"task": "run_ablation_repeated"})

    n_runs = int(cfg.get("n_runs", 1))
    instances = list(cfg["instances"])
    base_cfg = dict(cfg["eda_ts"])
    seed0 = int(cfg["seed"])

    run_rows: List[dict] = []
    cmetric_rows: List[dict] = []
    wilcoxon_rows: List[dict] = []

    start = time.time()
    for inst_idx, name in enumerate(instances, start=1):
        print(f"\n=== ablation {name} ({inst_idx}/{len(instances)}) ===")
        inst = load_instance_json(root / "data" / "sdmk01-15" / f"{name}.json")
        for run_idx in range(1, n_runs + 1):
            seed = seed0 + inst_idx * 10000 + run_idx
            cfg_full = EDATSConfig(seed=seed, **base_cfg)
            cfg_no_m = EDATSConfig(**{**cfg_full.__dict__, "use_multi_population": False})
            cfg_no_n = EDATSConfig(**{**cfg_full.__dict__, "use_nd_memory": False})
            cfg_no_mn = EDATSConfig(
                **{**cfg_full.__dict__, "use_multi_population": False, "use_nd_memory": False}
            )

            t0 = time.time()
            r_full = EDATS(inst, cfg_full).run()
            r_no_m = EDATS(inst, cfg_no_m).run()
            r_no_n = EDATS(inst, cfg_no_n).run()
            r_no_mn = EDATS(inst, cfg_no_mn).run()
            elapsed = time.time() - t0

            fronts = {
                "EDA-TS": to_front(r_full),
                "EDA-TS_no_m": to_front(r_no_m),
                "EDA-TS_no_n": to_front(r_no_n),
                "EDA-TS_no_mn": to_front(r_no_mn),
            }
            pf_true = build_pf_known(list(fronts.values()))

            for algo, front in fronts.items():
                run_rows.append(
                    {
                        "instance": name,
                        "run": run_idx,
                        "algorithm": algo,
                        "seed": seed,
                        "GD": gd(front, pf_true),
                        "IGD": igd(front, pf_true),
                        "runtime_s_total": elapsed,
                        "nd_size": len(front),
                    }
                )

            cmetric_rows.append(
                {
                    "instance": name,
                    "run": run_idx,
                    "pair": "EDA-TS_vs_no_m",
                    "c_ab": c_metric(fronts["EDA-TS"], fronts["EDA-TS_no_m"]),
                    "c_ba": c_metric(fronts["EDA-TS_no_m"], fronts["EDA-TS"]),
                }
            )
            cmetric_rows.append(
                {
                    "instance": name,
                    "run": run_idx,
                    "pair": "EDA-TS_vs_no_n",
                    "c_ab": c_metric(fronts["EDA-TS"], fronts["EDA-TS_no_n"]),
                    "c_ba": c_metric(fronts["EDA-TS_no_n"], fronts["EDA-TS"]),
                }
            )
            cmetric_rows.append(
                {
                    "instance": name,
                    "run": run_idx,
                    "pair": "EDA-TS_vs_no_mn",
                    "c_ab": c_metric(fronts["EDA-TS"], fronts["EDA-TS_no_mn"]),
                    "c_ba": c_metric(fronts["EDA-TS_no_mn"], fronts["EDA-TS"]),
                }
            )
            print(f"{name} run {run_idx}/{n_runs} done")

        # Wilcoxon rows.
        for competitor in ["EDA-TS_no_m", "EDA-TS_no_n", "EDA-TS_no_mn"]:
            base = [r for r in run_rows if r["instance"] == name and r["algorithm"] == "EDA-TS"]
            cmp = [r for r in run_rows if r["instance"] == name and r["algorithm"] == competitor]
            base = sorted(base, key=lambda x: int(x["run"]))
            cmp = sorted(cmp, key=lambda x: int(x["run"]))
            for metric in ["GD", "IGD"]:
                a = [float(r[metric]) for r in base]
                b = [float(r[metric]) for r in cmp]
                wm, p, win = wilcoxon_signed_rank(a, b, alpha=0.05, smaller_is_better=True)
                wilcoxon_rows.append(
                    {
                        "instance": name,
                        "competitor": competitor,
                        "metric": metric,
                        "Wm": wm,
                        "p_value": p,
                        "win": win,
                        "n_runs": len(a),
                    }
                )

    grouped: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for row in run_rows:
        grouped[(str(row["instance"]), str(row["algorithm"]))].append(row)
    summary_rows: List[dict] = []
    for (inst_name, algo), rows in sorted(grouped.items()):
        gd_vals = [float(r["GD"]) for r in rows]
        igd_vals = [float(r["IGD"]) for r in rows]
        nd_vals = [float(r["nd_size"]) for r in rows]
        summary_rows.append(
            {
                "instance": inst_name,
                "algorithm": algo,
                "mean_GD": sum(gd_vals) / len(gd_vals),
                "std_GD": _safe_std(gd_vals),
                "mean_IGD": sum(igd_vals) / len(igd_vals),
                "std_IGD": _safe_std(igd_vals),
                "mean_nd_size": sum(nd_vals) / len(nd_vals),
            }
        )

    def write_csv(path: Path, fieldnames: List[str], rows: List[dict]) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    write_csv(
        out_dir / "ablation_runs.csv",
        ["instance", "run", "algorithm", "seed", "GD", "IGD", "runtime_s_total", "nd_size"],
        run_rows,
    )
    write_csv(
        out_dir / "ablation_summary.csv",
        ["instance", "algorithm", "mean_GD", "std_GD", "mean_IGD", "std_IGD", "mean_nd_size"],
        summary_rows,
    )
    write_csv(out_dir / "ablation_cmetric_runs.csv", ["instance", "run", "pair", "c_ab", "c_ba"], cmetric_rows)
    write_csv(
        out_dir / "ablation_wilcoxon.csv",
        ["instance", "competitor", "metric", "Wm", "p_value", "win", "n_runs"],
        wilcoxon_rows,
    )
    print(f"saved to {out_dir}, elapsed={(time.time() - start) / 60.0:.2f} min")


if __name__ == "__main__":
    main()

