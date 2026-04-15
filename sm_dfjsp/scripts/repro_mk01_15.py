from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    parser.add_argument("--skip-taguchi", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    py = sys.executable

    run_cmd([py, "scripts/build_sdmk.py"], root)
    run_cmd([py, "scripts/validate_sdmk_dataset.py", "--out-dir", "reports/repro/validation"], root)

    if args.mode == "quick":
        compare_dir = "reports/repro/compare_01_15_quick"
        ablation_dir = "reports/repro/ablation_01_15_quick"
        compare_cfg = "configs/repro/experiment_01_15_quick.yaml"
        run_cmd(
            [
                py,
                "scripts/run_experiments_repeated.py",
                "--config",
                compare_cfg,
                "--out-dir",
                compare_dir,
            ],
            root,
        )
        run_cmd(
            [
                py,
                "scripts/run_ablation_repeated.py",
                "--config",
                "configs/repro/ablation_01_15_quick.yaml",
                "--out-dir",
                ablation_dir,
            ],
            root,
        )
        if not args.skip_taguchi:
            run_cmd(
                [
                    py,
                    "scripts/tune_params_taguchi.py",
                    "--instance",
                    "sdmk15",
                    "--runs-per-combo",
                    "2",
                    "--time-limit",
                    "8",
                    "--max-iter",
                    "3",
                    "--out-dir",
                    "reports/repro/taguchi_01_15_quick",
                ],
                root,
            )
    else:
        compare_dir = "reports/repro/compare_01_15"
        ablation_dir = "reports/repro/ablation_01_15"
        compare_cfg = "configs/repro/experiment_01_15.yaml"
        run_cmd(
            [
                py,
                "scripts/run_experiments_repeated.py",
                "--config",
                compare_cfg,
                "--out-dir",
                compare_dir,
            ],
            root,
        )
        run_cmd(
            [
                py,
                "scripts/run_ablation_repeated.py",
                "--config",
                "configs/repro/ablation_01_15.yaml",
                "--out-dir",
                ablation_dir,
            ],
            root,
        )
        if not args.skip_taguchi:
            run_cmd(
                [
                    py,
                    "scripts/tune_params_taguchi.py",
                    "--instance",
                    "sdmk15",
                    "--runs-per-combo",
                    "30",
                    "--time-limit",
                    "100",
                    "--max-iter",
                    "100",
                    "--out-dir",
                    "reports/repro/taguchi_01_15",
                ],
                root,
            )

    # Generate visualization artifacts:
    # - Pareto charts (per-instance + overall)
    # - C-metric heatmap / dominance matrix / dominance graph
    # - One Gantt chart per instance (EDA-TS, run=1) with explicit SRU labels
    run_cmd(
        [
            py,
            "scripts/visualize_repro_results.py",
            "--compare-dir",
            compare_dir,
            "--config",
            compare_cfg,
            "--out-dir",
            f"reports/repro/figures/{Path(compare_dir).name}",
            "--gantt-algorithm",
            "EDA-TS",
            "--gantt-run",
            "1",
            "--gantt-all-instances",
        ],
        root,
    )

    print("done: repro_mk01_15")


if __name__ == "__main__":
    main()

