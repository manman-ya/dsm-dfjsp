from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

from smdfjsp.core.encoding import build_option_index, build_random_individual, repair_individual
from smdfjsp.core.random_utils import make_rng
from smdfjsp.data.io import load_instance_json
from smdfjsp.model.evaluator import evaluate_individual

from repro_utils import write_run_meta


def validate_instance(path: Path, seed: int) -> Dict[str, object]:
    inst = load_instance_json(path)
    option_index = build_option_index(inst)
    problems: List[str] = []

    if inst.num_types <= 0:
        problems.append("num_types<=0")
    if not inst.jobs:
        problems.append("no_jobs")
    if not inst.srus:
        problems.append("no_srus")

    srus_by_type = inst.srus_by_type()
    unique_machine_sets_by_type = {
        t: len({tuple(sorted(s.machine_ids)) for s in srus}) for t, srus in srus_by_type.items()
    }
    all_same_machine_set = int(all(v <= 1 for v in unique_machine_sets_by_type.values()))
    for job in inst.jobs:
        if job.type_id not in srus_by_type:
            problems.append(f"job{job.job_id}:missing_type_sru")
            continue
        for s in srus_by_type[job.type_id]:
            if (job.job_id, s.sru_id) not in inst.transport_time:
                problems.append(f"job{job.job_id}:missing_t_{s.sru_id}")
            if (job.job_id, s.sru_id) not in inst.transport_cost_per_time:
                problems.append(f"job{job.job_id}:missing_ct_{s.sru_id}")

    rng = make_rng(seed)
    ind = build_random_individual(inst, option_index, rng)
    ind = repair_individual(ind, inst, option_index, rng)
    ev = evaluate_individual(inst, ind)
    if not ev.feasible:
        problems.append(f"infeasible_eval:{ev.message}")

    total_ops = sum(len(j.operations) for j in inst.jobs)
    total_options = sum(len(op.options) for j in inst.jobs for op in j.operations)
    return {
        "instance": inst.name,
        "jobs": len(inst.jobs),
        "srus": len(inst.srus),
        "ops": total_ops,
        "options": total_options,
        "feasible_eval": int(ev.feasible),
        "cost": ev.objectives[0],
        "makespan": ev.objectives[1],
        "all_same_machine_set": all_same_machine_set,
        "unique_machine_sets_by_type": ";".join(
            f"type{t}:{unique_machine_sets_by_type[t]}" for t in sorted(unique_machine_sets_by_type)
        ),
        "ok": int(len(problems) == 0),
        "problems": ";".join(problems),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/sdmk01-15")
    parser.add_argument("--out-dir", default="reports/repro/validation")
    parser.add_argument("--seed", type=int, default=20260408)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    data_dir = root / args.data_dir
    out_dir = root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    write_run_meta(out_dir, config_path=None, extra={"task": "validate_sdmk_dataset", "data_dir": str(data_dir)})

    files = sorted(data_dir.glob("sdmk*.json"))
    if not files:
        raise FileNotFoundError(f"No sdmk json found in {data_dir}")

    rows: List[Dict[str, object]] = []
    for i, f in enumerate(files):
        row = validate_instance(f, seed=args.seed + i)
        rows.append(row)
        print(
            f"{row['instance']}: ok={row['ok']} feasible_eval={row['feasible_eval']} "
            f"ops={row['ops']} options={row['options']}"
        )

    out_csv = out_dir / "validation_rows.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "instance",
                "jobs",
                "srus",
                "ops",
                "options",
                "feasible_eval",
                "cost",
                "makespan",
                "all_same_machine_set",
                "unique_machine_sets_by_type",
                "ok",
                "problems",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    fail = [r for r in rows if int(r["ok"]) == 0]
    summary = out_dir / "validation_summary.txt"
    summary.write_text(
        f"instances={len(rows)}\n"
        f"ok={len(rows) - len(fail)}\n"
        f"failed={len(fail)}\n"
        + ("\n".join(f"{r['instance']}:{r['problems']}" for r in fail) if fail else ""),
        encoding="utf-8",
    )
    print(f"saved: {out_csv}")
    print(f"saved: {summary}")


if __name__ == "__main__":
    main()
