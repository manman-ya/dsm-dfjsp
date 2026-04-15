from __future__ import annotations

import argparse
from pathlib import Path

from smdfjsp.data.io import load_instance_json
from smdfjsp.model.gurobi_model import solve_with_gurobi


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", default="sdmk01")
    parser.add_argument("--time-limit", type=float, default=60.0)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    inst = load_instance_json(root / "data" / "sdmk01-15" / f"{args.instance}.json")
    res = solve_with_gurobi(inst, time_limit_s=args.time_limit)
    print(
        {
            "status": res.status,
            "cost": res.objective_cost,
            "makespan": res.objective_makespan,
            "assigned_jobs": len(res.assignment),
        }
    )


if __name__ == "__main__":
    main()

