from __future__ import annotations

from pathlib import Path

from smdfjsp.data.dataset_builder import build_sdmk_dataset


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    build_sdmk_dataset(
        mk_dir=root / "data",
        spec_path=root / "configs" / "dataset_spec.yaml",
        output_dir=root / "data" / "sdmk01-15",
        manifest_path=root / "data" / "sdmk01-15" / "manifest.csv",
    )
    print("SDMK01-15 generated under data/sdmk01-15")


if __name__ == "__main__":
    main()

