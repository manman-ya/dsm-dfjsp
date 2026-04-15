from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ALGO_ORDER = ["EDA-TS", "EDA", "NSGA-II", "EDA-VNS", "H-GA-TS"]
COLORS = {
    "EDA-TS": "#1f77b4",
    "EDA": "#ff7f0e",
    "NSGA-II": "#2ca02c",
    "EDA-VNS": "#d62728",
    "H-GA-TS": "#9467bd",
}


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _plot_pareto(front_df: pd.DataFrame, out_dir: Path) -> List[Path]:
    saved: List[Path] = []
    for instance, grp in front_df.groupby("instance"):
        fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
        for algo in ALGO_ORDER:
            data = grp[grp["algorithm"] == algo]
            if data.empty:
                continue
            ax.scatter(
                data["cost"],
                data["makespan"],
                s=36,
                alpha=0.85,
                c=COLORS.get(algo, "#333333"),
                label=algo,
                edgecolors="white",
                linewidths=0.4,
            )
        ax.set_title(f"Pareto Front - {instance}")
        ax.set_xlabel("Total Cost")
        ax.set_ylabel("Makespan")
        ax.grid(alpha=0.25, linestyle="--")
        ax.legend(frameon=False)
        fig.tight_layout()
        out = out_dir / f"pareto_{instance}.png"
        fig.savefig(out)
        plt.close(fig)
        saved.append(out)
    return saved


def _plot_metric_heatmaps(metrics_df: pd.DataFrame, out_dir: Path) -> List[Path]:
    saved: List[Path] = []
    algo_df = metrics_df[metrics_df["algorithm"].isin(ALGO_ORDER)].copy()
    if algo_df.empty:
        return saved

    for metric in ["GD", "IGD"]:
        pivot = algo_df.pivot(index="instance", columns="algorithm", values=metric)
        pivot = pivot.reindex(columns=[c for c in ALGO_ORDER if c in pivot.columns])
        fig, ax = plt.subplots(figsize=(10, max(3, 0.6 * len(pivot.index))), dpi=150)
        mat = pivot.values.astype(float)
        im = ax.imshow(mat, aspect="auto", cmap="YlOrRd")
        ax.set_title(f"{metric} Heatmap")
        ax.set_xlabel("Algorithm")
        ax.set_ylabel("Instance")
        ax.set_xticks(np.arange(len(pivot.columns)))
        ax.set_xticklabels(pivot.columns, rotation=30, ha="right")
        ax.set_yticks(np.arange(len(pivot.index)))
        ax.set_yticklabels(pivot.index)
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                ax.text(j, i, f"{mat[i, j]:.3f}", ha="center", va="center", fontsize=7, color="black")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        fig.tight_layout()
        out = out_dir / f"heatmap_{metric.lower()}.png"
        fig.savefig(out)
        plt.close(fig)
        saved.append(out)

    return saved


def _plot_metric_boxplots(metrics_df: pd.DataFrame, out_dir: Path) -> List[Path]:
    saved: List[Path] = []
    algo_df = metrics_df[metrics_df["algorithm"].isin(ALGO_ORDER)].copy()
    if algo_df.empty:
        return saved

    for metric in ["GD", "IGD"]:
        series_data = []
        labels = []
        for algo in ALGO_ORDER:
            vals = algo_df.loc[algo_df["algorithm"] == algo, metric].dropna().values
            if len(vals) == 0:
                continue
            series_data.append(vals)
            labels.append(algo)
        if not series_data:
            continue

        fig, ax = plt.subplots(figsize=(9, 6), dpi=150)
        bp = ax.boxplot(series_data, patch_artist=True, tick_labels=labels, showmeans=True)
        for patch, lbl in zip(bp["boxes"], labels):
            patch.set_facecolor(COLORS.get(lbl, "#cccccc"))
            patch.set_alpha(0.55)
        for median in bp["medians"]:
            median.set_color("black")
            median.set_linewidth(1.2)
        ax.set_title(f"{metric} Boxplot Across Instances")
        ax.set_ylabel(metric)
        ax.grid(axis="y", alpha=0.25, linestyle="--")
        plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
        fig.tight_layout()
        out = out_dir / f"boxplot_{metric.lower()}.png"
        fig.savefig(out)
        plt.close(fig)
        saved.append(out)
    return saved


def _plot_metric_summary_bars(metrics_df: pd.DataFrame, out_dir: Path) -> List[Path]:
    saved: List[Path] = []
    algo_df = metrics_df[metrics_df["algorithm"].isin(ALGO_ORDER)].copy()
    if algo_df.empty:
        return saved

    for metric in ["GD", "IGD"]:
        stats = (
            algo_df.groupby("algorithm")[metric]
            .agg(["mean", "std", "count"])
            .reindex(ALGO_ORDER)
            .dropna(subset=["mean"])
            .reset_index()
        )
        if stats.empty:
            continue
        x = np.arange(len(stats))
        y = stats["mean"].values.astype(float)
        yerr = stats["std"].fillna(0.0).values.astype(float)
        colors = [COLORS.get(a, "#777777") for a in stats["algorithm"]]

        fig, ax = plt.subplots(figsize=(9, 6), dpi=150)
        ax.bar(x, y, yerr=yerr, capsize=4, color=colors, alpha=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(stats["algorithm"], rotation=20, ha="right")
        ax.set_ylabel(f"Average {metric}")
        ax.set_title(f"{metric} Summary (Mean ± Std)")
        ax.grid(axis="y", alpha=0.25, linestyle="--")
        for xi, yi in zip(x, y):
            ax.text(xi, yi, f"{yi:.3f}", ha="center", va="bottom", fontsize=8)
        fig.tight_layout()
        out = out_dir / f"summary_{metric.lower()}.png"
        fig.savefig(out)
        plt.close(fig)
        saved.append(out)
    return saved


def _build_cmetric_matrix(metric_grp: pd.DataFrame) -> Dict[Tuple[str, str], float]:
    """
    Parse rows like C(A,B) in 'algorithm' column.
    By convention in run_experiments.py:
    - GD column stores C(A,B)
    - IGD column stores C(B,A)
    """
    out: Dict[Tuple[str, str], float] = {}
    pat = re.compile(r"^C\((.+),(.+)\)$")
    for _, row in metric_grp.iterrows():
        s = str(row["algorithm"])
        m = pat.match(s)
        if not m:
            continue
        a, b = m.group(1).strip(), m.group(2).strip()
        out[(a, b)] = float(row["GD"])
        out[(b, a)] = float(row["IGD"])
    for algo in ALGO_ORDER:
        out[(algo, algo)] = 0.0
    return out


def _plot_cmetric_heatmaps(metrics_df: pd.DataFrame, out_dir: Path) -> List[Path]:
    saved: List[Path] = []
    for instance, grp in metrics_df.groupby("instance"):
        cm = _build_cmetric_matrix(grp)
        if not cm:
            continue
        algos = [a for a in ALGO_ORDER if any((a, b) in cm for b in ALGO_ORDER)]
        if not algos:
            continue
        mat = np.zeros((len(algos), len(algos)), dtype=float)
        for i, a in enumerate(algos):
            for j, b in enumerate(algos):
                mat[i, j] = cm.get((a, b), np.nan)

        fig, ax = plt.subplots(figsize=(7.5, 6.5), dpi=150)
        im = ax.imshow(mat, vmin=0, vmax=1, cmap="Blues")
        ax.set_title(f"C-metric Heatmap - {instance}")
        ax.set_xlabel("B in C(A,B)")
        ax.set_ylabel("A in C(A,B)")
        ax.set_xticks(np.arange(len(algos)))
        ax.set_xticklabels(algos, rotation=30, ha="right")
        ax.set_yticks(np.arange(len(algos)))
        ax.set_yticklabels(algos)
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                if np.isnan(mat[i, j]):
                    continue
                ax.text(j, i, f"{mat[i, j]:.3f}", ha="center", va="center", fontsize=8, color="black")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        fig.tight_layout()
        out = out_dir / f"cmetric_{instance}.png"
        fig.savefig(out)
        plt.close(fig)
        saved.append(out)
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", default="reports/smoke")
    args = parser.parse_args()

    report_dir = Path(args.report_dir).resolve()
    front_path = report_dir / "front_points.csv"
    metrics_path = report_dir / "metrics.csv"
    if not front_path.exists() or not metrics_path.exists():
        raise FileNotFoundError(
            f"front_points.csv or metrics.csv not found in {report_dir}. "
            "Run scripts/run_experiments.py first."
        )

    out_dir = report_dir / "figures"
    _ensure_dir(out_dir)
    front_df = pd.read_csv(front_path)
    metrics_df = pd.read_csv(metrics_path)

    saved = []
    saved += _plot_pareto(front_df, out_dir)
    saved += _plot_metric_heatmaps(metrics_df, out_dir)
    saved += _plot_metric_boxplots(metrics_df, out_dir)
    saved += _plot_metric_summary_bars(metrics_df, out_dir)
    saved += _plot_cmetric_heatmaps(metrics_df, out_dir)

    print(f"generated {len(saved)} figures in {out_dir}")
    for p in saved:
        print(p.as_posix())


if __name__ == "__main__":
    main()
