from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from smdfjsp.baselines import HGATSConfig, NSGAIIConfig, run_eda, run_eda_vns, run_h_gats, run_nsgaii
from smdfjsp.data.io import load_instance_json
from smdfjsp.eda_ts import EDATS, EDATSConfig
from smdfjsp.model.evaluator import evaluate_individual

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


def _load_cfg(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _plot_pareto_by_instance(front_df: pd.DataFrame, out_dir: Path) -> List[Path]:
    saved: List[Path] = []
    for instance, grp in front_df.groupby("instance"):
        fig, ax = plt.subplots(figsize=(8.5, 6.2), dpi=150)
        for algo in ALGO_ORDER:
            d = grp[grp["algorithm"] == algo]
            if d.empty:
                continue
            ax.scatter(
                d["cost"].to_numpy(dtype=float),
                d["makespan"].to_numpy(dtype=float),
                s=30,
                alpha=0.75,
                color=COLORS.get(algo, "#444444"),
                label=algo,
                edgecolors="white",
                linewidths=0.3,
            )
        ax.set_title(f"Pareto Front ({instance})")
        ax.set_xlabel("Total Cost")
        ax.set_ylabel("Makespan")
        ax.grid(alpha=0.25, linestyle="--")
        ax.legend(frameon=False, fontsize=8, ncol=2)
        fig.tight_layout()
        out = out_dir / f"pareto_{instance}.png"
        fig.savefig(out)
        plt.close(fig)
        saved.append(out)
    return saved


def _plot_pareto_overall(front_df: pd.DataFrame, out_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8.6, 6.2), dpi=150)
    for algo in ALGO_ORDER:
        d = front_df[front_df["algorithm"] == algo]
        if d.empty:
            continue
        ax.scatter(
            d["cost"].to_numpy(dtype=float),
            d["makespan"].to_numpy(dtype=float),
            s=16,
            alpha=0.5,
            color=COLORS.get(algo, "#444444"),
            label=algo,
            edgecolors="none",
        )
    ax.set_title("Pareto Front (All Instances/Runs)")
    ax.set_xlabel("Total Cost")
    ax.set_ylabel("Makespan")
    ax.grid(alpha=0.25, linestyle="--")
    ax.legend(frameon=False, fontsize=8, ncol=2)
    fig.tight_layout()
    out = out_dir / "pareto_overall.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def _mean_cmetric_matrix(cmetric_df: pd.DataFrame) -> pd.DataFrame:
    rows: List[Tuple[str, str, float]] = []
    for _, r in cmetric_df.iterrows():
        a = str(r["a"])
        b = str(r["b"])
        rows.append((a, b, float(r["c_ab"])))
        rows.append((b, a, float(r["c_ba"])))
    pivot = (
        pd.DataFrame(rows, columns=["a", "b", "c"])
        .groupby(["a", "b"], as_index=False)["c"]
        .mean()
        .pivot(index="a", columns="b", values="c")
        .reindex(index=ALGO_ORDER, columns=ALGO_ORDER)
    )
    for algo in ALGO_ORDER:
        pivot.loc[algo, algo] = 0.0
    return pivot


def _plot_cmetric_overall_heatmap(cmetric_df: pd.DataFrame, out_dir: Path) -> Path:
    mat_df = _mean_cmetric_matrix(cmetric_df)
    mat = mat_df.to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(7.8, 6.6), dpi=150)
    im = ax.imshow(mat, vmin=0.0, vmax=1.0, cmap="Blues")
    ax.set_title("C-metric Heatmap (Overall Mean)")
    ax.set_xlabel("B in C(A,B)")
    ax.set_ylabel("A in C(A,B)")
    ax.set_xticks(np.arange(len(ALGO_ORDER)))
    ax.set_xticklabels(ALGO_ORDER, rotation=25, ha="right")
    ax.set_yticks(np.arange(len(ALGO_ORDER)))
    ax.set_yticklabels(ALGO_ORDER)
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat[i, j]
            if math.isnan(v):
                continue
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    out = out_dir / "cmetric_heatmap_overall.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def _plot_edats_vs_others(cmetric_df: pd.DataFrame, out_dir: Path) -> List[Path]:
    saved: List[Path] = []
    d = cmetric_df[(cmetric_df["a"] == "EDA-TS") | (cmetric_df["b"] == "EDA-TS")].copy()
    if d.empty:
        return saved

    rows = []
    for comp in [a for a in ALGO_ORDER if a != "EDA-TS"]:
        ab = d[(d["a"] == "EDA-TS") & (d["b"] == comp)]["c_ab"].mean()
        ba = d[(d["a"] == comp) & (d["b"] == "EDA-TS")]["c_ab"].mean()
        rows.append({"competitor": comp, "C(EDA-TS,B)": ab, "C(B,EDA-TS)": ba})
    plot_df = pd.DataFrame(rows)

    x = np.arange(len(plot_df))
    w = 0.36
    fig, ax = plt.subplots(figsize=(9.2, 5.8), dpi=150)
    ax.bar(x - w / 2, plot_df["C(EDA-TS,B)"], width=w, label="C(EDA-TS,B)", color="#1f77b4", alpha=0.85)
    ax.bar(x + w / 2, plot_df["C(B,EDA-TS)"], width=w, label="C(B,EDA-TS)", color="#ff7f0e", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(plot_df["competitor"])
    ax.set_ylim(0.0, 1.0)
    ax.set_ylabel("C-metric")
    ax.set_title("EDA-TS vs Baselines (Overall Mean C-metric)")
    ax.grid(axis="y", alpha=0.25, linestyle="--")
    ax.legend(frameon=False)
    fig.tight_layout()
    out = out_dir / "cmetric_edats_vs_baselines.png"
    fig.savefig(out)
    plt.close(fig)
    saved.append(out)

    by_inst_rows = []
    for inst, grp in cmetric_df.groupby("instance"):
        for comp in [a for a in ALGO_ORDER if a != "EDA-TS"]:
            ab = grp[(grp["a"] == "EDA-TS") & (grp["b"] == comp)]["c_ab"].mean()
            ba = grp[(grp["a"] == comp) & (grp["b"] == "EDA-TS")]["c_ab"].mean()
            by_inst_rows.append({"instance": inst, "competitor": comp, "C(EDA-TS,B)": ab, "C(B,EDA-TS)": ba})
    by_inst_df = pd.DataFrame(by_inst_rows)

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), dpi=150, sharey=True)
    axes = axes.ravel()
    for i, comp in enumerate([a for a in ALGO_ORDER if a != "EDA-TS"]):
        ax = axes[i]
        sub = by_inst_df[by_inst_df["competitor"] == comp]
        ax.plot(sub["instance"], sub["C(EDA-TS,B)"], marker="o", label="C(EDA-TS,B)", color="#1f77b4")
        ax.plot(sub["instance"], sub["C(B,EDA-TS)"], marker="s", label="C(B,EDA-TS)", color="#ff7f0e")
        ax.set_title(f"EDA-TS vs {comp}")
        ax.set_ylim(0.0, 1.0)
        ax.grid(alpha=0.25, linestyle="--")
        ax.tick_params(axis="x", rotation=45)
        if i in (0, 2):
            ax.set_ylabel("C-metric")
        if i in (2, 3):
            ax.set_xlabel("Instance")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = out_dir / "cmetric_edats_vs_baselines_by_instance.png"
    fig.savefig(out)
    plt.close(fig)
    saved.append(out)

    return saved


def _plot_dominance_graph(cmetric_df: pd.DataFrame, out_dir: Path) -> List[Path]:
    saved: List[Path] = []
    mat_df = _mean_cmetric_matrix(cmetric_df)
    dom = mat_df - mat_df.T
    arr = dom.to_numpy(dtype=float)

    fig, ax = plt.subplots(figsize=(8.2, 6.8), dpi=150)
    im = ax.imshow(arr, cmap="RdBu_r", vmin=-1.0, vmax=1.0)
    ax.set_title("Dominance Difference Matrix: C(A,B)-C(B,A)")
    ax.set_xticks(np.arange(len(ALGO_ORDER)))
    ax.set_xticklabels(ALGO_ORDER, rotation=25, ha="right")
    ax.set_yticks(np.arange(len(ALGO_ORDER)))
    ax.set_yticklabels(ALGO_ORDER)
    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            v = arr[i, j]
            if math.isnan(v):
                continue
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    out = out_dir / "dominance_matrix_overall.png"
    fig.savefig(out)
    plt.close(fig)
    saved.append(out)

    n = len(ALGO_ORDER)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    radius = 1.0
    coords = {a: (radius * np.cos(ang), radius * np.sin(ang)) for a, ang in zip(ALGO_ORDER, angles)}

    fig, ax = plt.subplots(figsize=(8, 8), dpi=150)
    ax.set_title("Algorithm Dominance Graph (Overall)")
    for algo, (x, y) in coords.items():
        ax.scatter([x], [y], s=900, color=COLORS.get(algo, "#777777"), alpha=0.85, zorder=3)
        ax.text(x, y, algo, ha="center", va="center", color="white", fontsize=9, weight="bold", zorder=4)

    for a in ALGO_ORDER:
        for b in ALGO_ORDER:
            if a == b:
                continue
            diff = dom.loc[a, b]
            if math.isnan(diff) or diff <= 0.02:
                continue
            x1, y1 = coords[a]
            x2, y2 = coords[b]
            ax.annotate(
                "",
                xy=(x2, y2),
                xytext=(x1, y1),
                arrowprops=dict(
                    arrowstyle="->",
                    lw=1.0 + 4.0 * float(diff),
                    color=COLORS.get(a, "#333333"),
                    alpha=0.6,
                    shrinkA=22,
                    shrinkB=22,
                ),
                zorder=2,
            )
            mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            ax.text(mx, my, f"{float(diff):.2f}", fontsize=7, color="#222222")

    ax.set_xlim(-1.35, 1.35)
    ax.set_ylim(-1.35, 1.35)
    ax.axis("off")
    fig.tight_layout()
    out = out_dir / "dominance_graph_overall.png"
    fig.savefig(out)
    plt.close(fig)
    saved.append(out)
    return saved


def _build_runner(inst, cfg: dict, algo: str, seed: int):
    if algo == "EDA-TS":
        return EDATS(inst, EDATSConfig(seed=seed, **cfg["eda_ts"])).run
    if algo == "EDA":
        return lambda: run_eda(inst, EDATSConfig(seed=seed, **cfg["eda"]))
    if algo == "NSGA-II":
        return lambda: run_nsgaii(inst, NSGAIIConfig(seed=seed, **cfg["nsgaii"]))
    if algo == "EDA-VNS":
        return lambda: run_eda_vns(inst, EDATSConfig(seed=seed, **cfg["eda_vns"]))
    if algo == "H-GA-TS":
        return lambda: run_h_gats(inst, HGATSConfig(seed=seed, **cfg["h_gats"]))
    raise ValueError(f"Unsupported algorithm: {algo}")


def _pick_seed(metrics_runs: pd.DataFrame, instance: str, algorithm: str, run_id: int, default_seed: int) -> int:
    sub = metrics_runs[
        (metrics_runs["instance"] == instance)
        & (metrics_runs["algorithm"] == algorithm)
        & (metrics_runs["run"] == run_id)
    ]
    if sub.empty:
        return default_seed
    return int(sub.iloc[0]["seed"])


def _plot_gantt(
    data_dir: Path,
    cfg: dict,
    metrics_runs: pd.DataFrame,
    out_dir: Path,
    instance: str,
    algorithm: str,
    run_id: int,
) -> Path:
    inst = load_instance_json(data_dir / f"{instance}.json")
    default_seed = int(cfg.get("seed", 20260408))
    seed = _pick_seed(metrics_runs, instance, algorithm, run_id, default_seed)

    run_result = _build_runner(inst, cfg, algorithm, seed)()
    sols = [x for x in run_result.nd_solutions if x.objectives is not None]
    if not sols:
        raise RuntimeError(f"No feasible solutions from {algorithm} on {instance}.")
    best = min(sols, key=lambda s: (s.objectives[0], s.objectives[1]))  # type: ignore[index]
    ev = evaluate_individual(inst, best)
    records = ev.records

    lanes = sorted({(r.sru_id, r.machine_id) for r in records}, key=lambda x: (x[0], x[1]))
    lane_pos = {lane: i for i, lane in enumerate(lanes)}
    cmap = plt.get_cmap("tab20")
    job_ids = sorted({r.job_id for r in records})
    job_color = {jid: cmap(i % 20) for i, jid in enumerate(job_ids)}

    fig_h = max(4.5, 0.5 * len(lanes) + 2)
    fig, ax = plt.subplots(figsize=(13, fig_h), dpi=150)

    for r in records:
        y = lane_pos[(r.sru_id, r.machine_id)]
        ax.barh(
            y,
            r.end - r.start,
            left=r.start,
            height=0.7,
            color=job_color[r.job_id],
            edgecolor="black",
            linewidth=0.3,
            alpha=0.9,
        )
        if (r.end - r.start) >= 1.5:
            ax.text(r.start + 0.1, y, f"J{r.job_id}-O{r.op_id}", va="center", ha="left", fontsize=7)

    ax.set_yticks(range(len(lanes)))
    ax.set_yticklabels([f"SRU{sid}-M{mid}" for sid, mid in lanes])
    # Highlight SRU groups so each SRU is visually explicit.
    grouped: Dict[int, List[int]] = {}
    for i, (sid, _) in enumerate(lanes):
        grouped.setdefault(sid, []).append(i)
    for sid, idxs in grouped.items():
        y0 = min(idxs) - 0.45
        y1 = max(idxs) + 0.45
        ax.axhline(y=y0, color="#888888", linewidth=0.6, alpha=0.6)
        ax.axhline(y=y1, color="#888888", linewidth=0.6, alpha=0.6)
        yc = (y0 + y1) / 2.0
        ax.text(
            -0.01,
            yc,
            f"SRU{sid}",
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=8,
            color="#333333",
            clip_on=False,
        )

    ax.set_xlabel("Time")
    ax.set_ylabel("SRU-Machine")
    proc_mk = max((r.end for r in records), default=0.0)
    ax.set_title(
        f"Gantt ({instance}, {algorithm}, run={run_id}, seed={seed}) | "
        f"cost={ev.objectives[0]:.1f}, makespan={ev.objectives[1]:.1f}, proc_end={proc_mk:.1f}"
    )
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    fig.tight_layout()

    out = out_dir / f"gantt_{instance}_{algorithm.replace('-', '')}_run{run_id}.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare-dir", default="reports/repro/compare_01_15_quick")
    parser.add_argument("--config", default="configs/repro/experiment_01_15_quick.yaml")
    parser.add_argument("--data-dir", default="data/sdmk01-15")
    parser.add_argument("--out-dir", default="reports/repro/figures/compare_01_15_quick")
    parser.add_argument("--gantt-instance", default="sdmk01")
    parser.add_argument("--gantt-algorithm", default="EDA-TS", choices=ALGO_ORDER)
    parser.add_argument("--gantt-run", type=int, default=1)
    parser.add_argument("--gantt-all-instances", action="store_true")
    parser.add_argument("--gantt-only", action="store_true")
    parser.add_argument("--skip-gantt", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    compare_dir = root / args.compare_dir
    cfg_path = root / args.config
    data_dir = root / args.data_dir
    out_dir = root / args.out_dir
    _ensure_dir(out_dir)

    front_path = compare_dir / "front_points.csv"
    metrics_runs_path = compare_dir / "metrics_runs.csv"
    cmetric_path = compare_dir / "cmetric_runs.csv"
    for p in [front_path, metrics_runs_path, cmetric_path]:
        if not p.exists():
            raise FileNotFoundError(f"Missing required file: {p}")

    cfg = _load_cfg(cfg_path)
    front_df = pd.read_csv(front_path)
    metrics_runs = pd.read_csv(metrics_runs_path)
    cmetric_df = pd.read_csv(cmetric_path)

    saved: List[Path] = []
    if not args.gantt_only:
        saved += _plot_pareto_by_instance(front_df, out_dir)
        saved.append(_plot_pareto_overall(front_df, out_dir))
        saved.append(_plot_cmetric_overall_heatmap(cmetric_df, out_dir))
        saved += _plot_edats_vs_others(cmetric_df, out_dir)
        saved += _plot_dominance_graph(cmetric_df, out_dir)
    if not args.skip_gantt:
        if args.gantt_all_instances:
            instances = sorted(metrics_runs["instance"].dropna().unique().tolist())
            for inst_name in instances:
                saved.append(
                    _plot_gantt(
                        data_dir=data_dir,
                        cfg=cfg,
                        metrics_runs=metrics_runs,
                        out_dir=out_dir,
                        instance=str(inst_name),
                        algorithm=args.gantt_algorithm,
                        run_id=args.gantt_run,
                    )
                )
        else:
            saved.append(
                _plot_gantt(
                    data_dir=data_dir,
                    cfg=cfg,
                    metrics_runs=metrics_runs,
                    out_dir=out_dir,
                    instance=args.gantt_instance,
                    algorithm=args.gantt_algorithm,
                    run_id=args.gantt_run,
                )
            )

    print(f"generated {len(saved)} figures in {out_dir}")
    for p in saved:
        print(p.as_posix())


if __name__ == "__main__":
    main()
