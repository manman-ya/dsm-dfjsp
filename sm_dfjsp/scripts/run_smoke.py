from __future__ import annotations

from pathlib import Path

from smdfjsp.data.dataset_builder import build_sdmk_dataset
from smdfjsp.data.io import load_instance_json
from smdfjsp.eda_ts import EDATS, EDATSConfig


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sdmk_dir = root / "data" / "sdmk01-15"
    sample_file = sdmk_dir / "sdmk01.json"
    if not sample_file.exists():
        build_sdmk_dataset(
            mk_dir=root / "data",
            spec_path=root / "configs" / "dataset_spec.yaml",
            output_dir=sdmk_dir,
            manifest_path=sdmk_dir / "manifest.csv",
        )
    inst = load_instance_json(sample_file)
    cfg = EDATSConfig(
        popsize=20,
        max_iter=5,
        time_limit_s=10.0,
        alpha=0.5,
        beta=0.5,
        gamma=0.5,
        mu=0.1,
        epsilon=0.008,
        tmax=2,
        seed=20260408,
    )
    algo = EDATS(inst, cfg)
    result = algo.run()
    objs = sorted({(round(x.objectives[0], 2), round(x.objectives[1], 2)) for x in result.nd_solutions if x.objectives})
    print(f"smoke done: nd_size={len(objs)}")
    for obj in objs[:10]:
        print(obj)


if __name__ == "__main__":
    main()

