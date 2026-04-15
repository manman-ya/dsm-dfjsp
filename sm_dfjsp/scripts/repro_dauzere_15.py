from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list[str], cwd: Path) -> None:
    print(">>", " ".join(cmd))
    env = os.environ.copy()
    src_path = str((cwd / "src").resolve())
    old_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_path if not old_pp else f"{src_path}{os.pathsep}{old_pp}"
    subprocess.run(cmd, cwd=cwd, check=True, env=env)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    py = sys.executable

    # Build dauzere SDMK-style dataset from txt sources.
    run_cmd([py, "scripts/build_sdmk_dauzere.py"], root)

    # Validate converted dauzere instances.
    run_cmd(
        [
            py,
            "scripts/validate_sdmk_dataset.py",
            "--data-dir",
            "data/dauzere",
            "--out-dir",
            "reports/repro/validation_dauzere_15runs",
        ],
        root,
    )

    # Full-style repeated comparison (15 runs), no ablation.
    run_cmd(
        [
            py,
            "scripts/run_experiments_repeated.py",
            "--config",
            "configs/repro/experiment_dauzere_15runs.yaml",
            "--data-dir",
            "data/dauzere",
            "--out-dir",
            "reports/repro/compare_dauzere_15runs",
        ],
        root,
    )

    # Visualize compare outputs and produce one Gantt per instance.
    run_cmd(
        [
            py,
            "scripts/visualize_repro_results.py",
            "--compare-dir",
            "reports/repro/compare_dauzere_15runs",
            "--config",
            "configs/repro/experiment_dauzere_15runs.yaml",
            "--data-dir",
            "data/dauzere",
            "--out-dir",
            "reports/repro/figures/compare_dauzere_15runs",
            "--gantt-algorithm",
            "EDA-TS",
            "--gantt-run",
            "1",
            "--gantt-all-instances",
        ],
        root,
    )

    print("done: repro_dauzere_15")


if __name__ == "__main__":
    main()
