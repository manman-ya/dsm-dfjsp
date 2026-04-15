from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _ensure(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_table7(compare_dir: Path, out_dir: Path) -> None:
    df = pd.read_csv(compare_dir / "metrics_summary.csv")
    pivot_gd = df.pivot(index="instance", columns="algorithm", values="mean_GD")
    pivot_igd = df.pivot(index="instance", columns="algorithm", values="mean_IGD")
    pivot_rt = df.pivot(index="instance", columns="algorithm", values="mean_runtime_s")
    table7 = (
        pivot_gd.add_prefix("GD_")
        .join(pivot_igd.add_prefix("IGD_"), how="outer")
        .join(pivot_rt.add_prefix("RT_"), how="outer")
        .reset_index()
        .sort_values("instance")
    )
    table7.to_csv(out_dir / "table7_compare_gd_igd_runtime.csv", index=False)


def build_table8(compare_dir: Path, out_dir: Path) -> None:
    df = pd.read_csv(compare_dir / "cmetric_runs.csv")
    agg = (
        df.groupby(["instance", "a", "b"], as_index=False)[["c_ab", "c_ba"]]
        .mean()
        .rename(columns={"c_ab": "mean_c_ab", "c_ba": "mean_c_ba"})
    )
    agg.to_csv(out_dir / "table8_compare_cmetric.csv", index=False)


def build_table11(ablation_dir: Path, out_dir: Path) -> None:
    df = pd.read_csv(ablation_dir / "ablation_summary.csv")
    table11 = df[["instance", "algorithm", "mean_GD", "mean_IGD"]].sort_values(["instance", "algorithm"])
    table11.to_csv(out_dir / "table11_ablation_gd_igd.csv", index=False)


def build_table12(ablation_dir: Path, out_dir: Path) -> None:
    df = pd.read_csv(ablation_dir / "ablation_cmetric_runs.csv")
    agg = (
        df.groupby(["instance", "pair"], as_index=False)[["c_ab", "c_ba"]]
        .mean()
        .rename(columns={"c_ab": "mean_c_ab", "c_ba": "mean_c_ba"})
        .sort_values(["instance", "pair"])
    )
    agg.to_csv(out_dir / "table12_ablation_cmetric.csv", index=False)


def build_table13(ablation_dir: Path, out_dir: Path) -> None:
    df = pd.read_csv(ablation_dir / "ablation_wilcoxon.csv")
    df = df.sort_values(["instance", "competitor", "metric"])
    df.to_csv(out_dir / "table13_ablation_wilcoxon.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare-dir", default="reports/repro/compare_01_15")
    parser.add_argument("--ablation-dir", default="reports/repro/ablation_01_15")
    parser.add_argument("--out-dir", default="reports/repro/tables")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    compare_dir = root / args.compare_dir
    ablation_dir = root / args.ablation_dir
    out_dir = root / args.out_dir
    _ensure(out_dir)

    missing = [p for p in [compare_dir / "metrics_summary.csv", ablation_dir / "ablation_summary.csv"] if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required csv: {[str(x) for x in missing]}")

    build_table7(compare_dir, out_dir)
    build_table8(compare_dir, out_dir)
    build_table11(ablation_dir, out_dir)
    build_table12(ablation_dir, out_dir)
    build_table13(ablation_dir, out_dir)
    print(f"tables saved in {out_dir}")


if __name__ == "__main__":
    main()

