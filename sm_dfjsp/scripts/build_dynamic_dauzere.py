from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

import yaml

from smdfjsp.data.dataset_builder import convert_static_instance_to_dynamic, generate_release_time_map
from smdfjsp.data.io import load_instance_json, save_instance_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Build dynamic dauzere dataset from existing sdmk*.json files.")
    parser.add_argument("--config", default="configs/dynamic_dauzere.yaml")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))

    source_dir = root / cfg.get("source_dir", "data/dauzere")
    output_dir = root / cfg.get("output_dir", "data/dauzere_dynamic")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / cfg.get("manifest_name", "manifest_dynamic.csv")

    pattern = str(cfg.get("pattern", "sdmk*.json"))
    seed = int(cfg.get("seed", 20260408))
    initial_job_ratio = float(cfg.get("initial_job_ratio", 0.4))
    t_range = tuple(cfg.get("arrival_time_range", [5, 120]))
    release_step = int(cfg.get("release_time_step", 5))
    name_suffix = str(cfg.get("name_suffix", "_dyn"))

    source_files = sorted(source_dir.glob(pattern))
    if not source_files:
        raise FileNotFoundError(f"No source json matched '{pattern}' under {source_dir}")

    rows: List[Dict[str, object]] = []
    for idx, src in enumerate(source_files):
        inst = load_instance_json(src)
        job_ids = [j.job_id for j in inst.jobs]
        rel_map, initial_jobs = generate_release_time_map(
            job_ids=job_ids,
            seed=seed + idx,
            initial_job_ratio=initial_job_ratio,
            arrival_time_range=(int(t_range[0]), int(t_range[1])),
            step=release_step,
        )
        dyn = convert_static_instance_to_dynamic(
            instance=inst,
            release_time_by_job=rel_map,
            initial_jobs=initial_jobs,
            dynamic_tag="dauzere_dynamic_release_time",
        )
        dyn.name = f"{inst.name}{name_suffix}"
        dyn.metadata["dynamic_source"] = "dauzere_json"
        dyn.metadata["dynamic_seed"] = seed + idx
        dyn.metadata["initial_job_ratio"] = initial_job_ratio
        dyn.metadata["arrival_time_range"] = [int(t_range[0]), int(t_range[1])]
        dyn.metadata["release_time_step"] = release_step
        out_file = output_dir / f"{dyn.name}.json"
        save_instance_json(dyn, out_file)
        n_initial = len([j for j in dyn.jobs if j.release_time <= 0.0])
        rows.append(
            {
                "instance": dyn.name,
                "source": src.name,
                "jobs": len(dyn.jobs),
                "initial_jobs": n_initial,
                "future_jobs": len(dyn.jobs) - n_initial,
                "arrival_events": len(dyn.arrival_stream),
                "seed": seed + idx,
                "file": out_file.relative_to(root).as_posix(),
            }
        )

    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["instance", "source", "jobs", "initial_jobs", "future_jobs", "arrival_events", "seed", "file"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Dynamic dataset generated: {len(rows)} instances")
    print(f"Output dir: {output_dir}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
