from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List

from smdfjsp.data.dataset_builder import convert_mk_to_sdmk, load_dataset_spec
from smdfjsp.data.io import save_instance_json
from smdfjsp.data.mk_parser import parse_mk_file


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    input_dir = root / "data" / "dauzere"
    output_dir = input_dir
    spec_path = root / "configs" / "dataset_spec.yaml"
    manifest_path = output_dir / "manifest.csv"

    spec = load_dataset_spec(spec_path)
    source_files = sorted(input_dir.glob("*.txt"))
    if not source_files:
        raise FileNotFoundError(f"No dauzere txt found under {input_dir}")

    rows: List[Dict[str, object]] = []
    for idx, src_file in enumerate(source_files):
        mk = parse_mk_file(src_file)
        inst = convert_mk_to_sdmk(mk, spec, seed_offset=idx)
        inst.name = f"sdmk{mk.name}"
        inst.metadata["source_set"] = "dauzere"
        inst.metadata["source_instance"] = mk.name

        out_file = output_dir / f"{inst.name}.json"
        save_instance_json(inst, out_file)

        total_ops = sum(len(j.operations) for j in inst.jobs)
        total_options = sum(len(op.options) for j in inst.jobs for op in j.operations)
        rows.append(
            {
                "instance": inst.name,
                "source_instance": mk.name,
                "jobs": len(inst.jobs),
                "types": inst.num_types,
                "srus": len(inst.srus),
                "ops": total_ops,
                "options": total_options,
                "seed": inst.metadata["seed"],
                "file": out_file.relative_to(root).as_posix(),
            }
        )

    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "instance",
                "source_instance",
                "jobs",
                "types",
                "srus",
                "ops",
                "options",
                "seed",
                "file",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} instances under {output_dir}")
    print(f"Manifest saved to {manifest_path}")


if __name__ == "__main__":
    main()
