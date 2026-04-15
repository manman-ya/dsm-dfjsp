from __future__ import annotations

import csv
from pathlib import Path

from smdfjsp.data.io import load_instance_json
from smdfjsp.eda_ts import EDATS, EDATSConfig
from smdfjsp.metrics import build_pf_known, c_metric, gd, igd


def to_front(res):
    return [(float(x.objectives[0]), float(x.objectives[1])) for x in res.nd_solutions if x.objectives is not None]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    instances = [f"sdmk{i:02d}" for i in range(1, 16)]
    out_dir = root / "reports" / "ablation"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    for name in instances:
        inst = load_instance_json(root / "data" / "sdmk01-15" / f"{name}.json")
        base = EDATSConfig(
            popsize=50,
            max_iter=100,
            time_limit_s=100.0,
            alpha=0.5,
            beta=0.5,
            gamma=0.5,
            mu=0.1,
            epsilon=0.008,
            tmax=10,
            seed=20260408,
        )
        r_full = EDATS(inst, base).run()
        no_m = EDATS(inst, EDATSConfig(**{**base.__dict__, "use_multi_population": False})).run()
        no_n = EDATS(inst, EDATSConfig(**{**base.__dict__, "use_nd_memory": False})).run()
        no_mn = EDATS(
            inst, EDATSConfig(**{**base.__dict__, "use_multi_population": False, "use_nd_memory": False})
        ).run()

        fronts = {
            "EDA-TS": to_front(r_full),
            "EDA-TS_no_m": to_front(no_m),
            "EDA-TS_no_n": to_front(no_n),
            "EDA-TS_no_mn": to_front(no_mn),
        }
        pf_true = build_pf_known(list(fronts.values()))
        for algo, front in fronts.items():
            rows.append({"instance": name, "algorithm": algo, "GD": gd(front, pf_true), "IGD": igd(front, pf_true)})
        rows.append(
            {
                "instance": name,
                "algorithm": "C(EDA-TS,no_m)",
                "GD": c_metric(fronts["EDA-TS"], fronts["EDA-TS_no_m"]),
                "IGD": c_metric(fronts["EDA-TS_no_m"], fronts["EDA-TS"]),
            }
        )
        rows.append(
            {
                "instance": name,
                "algorithm": "C(EDA-TS,no_n)",
                "GD": c_metric(fronts["EDA-TS"], fronts["EDA-TS_no_n"]),
                "IGD": c_metric(fronts["EDA-TS_no_n"], fronts["EDA-TS"]),
            }
        )
        rows.append(
            {
                "instance": name,
                "algorithm": "C(EDA-TS,no_mn)",
                "GD": c_metric(fronts["EDA-TS"], fronts["EDA-TS_no_mn"]),
                "IGD": c_metric(fronts["EDA-TS_no_mn"], fronts["EDA-TS"]),
            }
        )
        print(f"ablation done: {name}")

    with (out_dir / "ablation_metrics.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["instance", "algorithm", "GD", "IGD"])
        w.writeheader()
        w.writerows(rows)
    print(f"saved: {out_dir / 'ablation_metrics.csv'}")


if __name__ == "__main__":
    main()

