from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def _plot_ablation_summary(ablation_dir: Path, out_dir: Path) -> None:
    df = pd.read_csv(ablation_dir / "ablation_summary.csv")
    for metric in ["mean_GD", "mean_IGD"]:
        pivot = df.pivot(index="instance", columns="algorithm", values=metric)
        fig, ax = plt.subplots(figsize=(11, 5), dpi=140)
        pivot.mean(axis=0).sort_values().plot(kind="bar", ax=ax)
        ax.set_title(f"Ablation {metric} (mean over instances)")
        ax.set_ylabel(metric)
        ax.grid(axis="y", linestyle="--", alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / f"ablation_{metric}.png")
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare-dir", default="reports/repro/compare_01_15")
    parser.add_argument("--ablation-dir", default="reports/repro/ablation_01_15")
    parser.add_argument("--out-dir", default="reports/repro/figures")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    compare_dir = root / args.compare_dir
    ablation_dir = root / args.ablation_dir
    out_dir = root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Reuse existing comparison plotting pipeline.
    subprocess.run(
        [sys.executable, "scripts/plot_results.py", "--report-dir", str(compare_dir)],
        cwd=root,
        check=True,
    )
    # Build extra ablation summary figures.
    _plot_ablation_summary(ablation_dir, out_dir)
    print(f"figures saved in {out_dir}")


if __name__ == "__main__":
    main()

