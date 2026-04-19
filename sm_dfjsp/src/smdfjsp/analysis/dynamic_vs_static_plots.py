from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from smdfjsp.core.types import ObjPair, ScheduleRecord


def plot_pareto_front_vs_dynamic_points(
    static_front: List[ObjPair],
    dynamic_rows: List[Dict[str, object]],
    out_path: Path,
    title: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
    if static_front:
        xs = [x[0] for x in static_front]
        ys = [x[1] for x in static_front]
        ax.plot(xs, ys, color="black", linewidth=1.5, marker="o", markersize=4, label="static_front")

    color_map = {
        "cost_then_makespan": "#1f77b4",
        "min_makespan": "#ff7f0e",
        "knee": "#2ca02c",
        "random": "#d62728",
        "none": "#9467bd",
    }
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for row in dynamic_rows:
        policy = str(row.get("selection_policy", "none"))
        grouped.setdefault(policy, []).append(row)
    for policy, rows in sorted(grouped.items()):
        xs = [float(x["total_cost"]) for x in rows]
        ys = [float(x["makespan"]) for x in rows]
        ax.scatter(xs, ys, s=28, alpha=0.75, color=color_map.get(policy, "#8c564b"), label=f"dynamic_{policy}")
    ax.set_xlabel("total_cost")
    ax.set_ylabel("makespan")
    ax.set_title(title)
    ax.grid(alpha=0.25, linestyle="--")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def plot_distance_to_front(
    rows: List[Dict[str, object]],
    out_path: Path,
    title: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    grouped: Dict[str, List[float]] = {}
    for row in rows:
        policy = str(row.get("selection_policy", "none"))
        grouped.setdefault(policy, []).append(float(row["distance_to_static_front"]))
    policies = sorted(grouped.keys())
    means = [sum(grouped[p]) / len(grouped[p]) for p in policies]
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    ax.bar(policies, means, color="#4c78a8")
    ax.set_xlabel("selection_policy")
    ax.set_ylabel("distance_to_static_front")
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.25, linestyle="--")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def plot_gap_to_front(
    rows: List[Dict[str, object]],
    out_path: Path,
    title: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    grouped_cost: Dict[str, List[float]] = {}
    grouped_mk: Dict[str, List[float]] = {}
    for row in rows:
        policy = str(row.get("selection_policy", "none"))
        grouped_cost.setdefault(policy, []).append(float(row["cost_gap_to_front"]))
        grouped_mk.setdefault(policy, []).append(float(row["makespan_gap_to_front"]))
    policies = sorted(grouped_cost.keys())
    cost_vals = [sum(grouped_cost[p]) / len(grouped_cost[p]) for p in policies]
    mk_vals = [sum(grouped_mk[p]) / len(grouped_mk[p]) for p in policies]

    x = list(range(len(policies)))
    width = 0.36
    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    ax.bar([i - width / 2 for i in x], cost_vals, width=width, label="cost_gap_to_front", color="#f58518")
    ax.bar([i + width / 2 for i in x], mk_vals, width=width, label="makespan_gap_to_front", color="#54a24b")
    ax.set_xticks(x)
    ax.set_xticklabels(policies)
    ax.set_xlabel("selection_policy")
    ax.set_ylabel("relative_gap")
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.25, linestyle="--")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def plot_metric_bars(
    rows: List[Dict[str, object]],
    metric: str,
    out_path: Path,
    title: str,
    method_order: Iterable[str],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    grouped: Dict[str, List[float]] = {}
    for row in rows:
        key = str(row.get("method_label", row.get("method", "")))
        grouped.setdefault(key, []).append(float(row[metric]))
    labels = [x for x in method_order if x in grouped]
    vals = [sum(grouped[k]) / len(grouped[k]) for k in labels]
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    ax.bar(labels, vals, color="#4c78a8")
    ax.set_xlabel("method")
    ax.set_ylabel(metric)
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.25, linestyle="--")
    ax.tick_params(axis="x", rotation=15)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def plot_rescheduling_timeline(
    arrival_times: List[float],
    policy_event_logs: Dict[str, List[Dict[str, object]]],
    completion_times: Dict[str, float],
    out_path: Path,
    title: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 5), dpi=150)
    policies = sorted(policy_event_logs.keys())
    for y, policy in enumerate(policies):
        logs = policy_event_logs[policy]
        reschedule_times = [float(x["time"]) for x in logs if "reschedule" in list(x.get("tags", []))]
        ax.scatter(reschedule_times, [y] * len(reschedule_times), color="#d62728", s=18, label=None)
        finish_t = float(completion_times.get(policy, 0.0))
        ax.scatter([finish_t], [y], marker="x", color="black", s=45)
    if arrival_times:
        ax.vlines(arrival_times, ymin=-0.5, ymax=max(0.5, len(policies) - 0.5), colors="#999999", linewidth=0.8, alpha=0.35)
    ax.set_yticks(range(len(policies)))
    ax.set_yticklabels(policies)
    ax.set_xlabel("time")
    ax.set_ylabel("selection_policy")
    ax.set_title(title)
    ax.grid(axis="x", alpha=0.25, linestyle="--")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def plot_dynamic_gantt(
    records: List[ScheduleRecord],
    reschedule_times: List[float],
    out_path: Path,
    title: str,
    *,
    arrival_times: Optional[List[float]] = None,
    show_labels: bool = True,
    label_min_width: float = 60.0,
    color_by: str = "job",
    show_arrival_lines: bool = False,
    show_reschedule_lines: bool = True,
    event_line_alpha: float = 0.25,
    focus_on_active_horizon: bool = True,
    show_frozen_hatch: bool = True,
    split_by_sru: bool = False,
    time_window: Optional[Tuple[float, float]] = None,
    annotate_mode: str = "auto",
    frozen_split_time: Optional[float] = None,
    max_event_lines: int = 24,
    legend_max_jobs: int = 14,
) -> None:
    """
    Plot dynamic gantt with paper-oriented readability defaults.

    Readability-focused behaviors:
    - Focus x-range to active horizon (near makespan) to avoid compressed bars.
    - Consistent color-by-job mapping across machines.
    - Adaptive operation labels (skip narrow/overcrowded bars).
    - Subtle arrival/reschedule lines with optional sparsification.
    - Distinguish frozen prefix vs newly assigned operations by hatch/border style.
    - Optional SRU group splitting or separators for structure.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lanes = sorted({(r.sru_id, r.machine_id) for r in records}, key=lambda x: (x[0], x[1]))
    fig_h = max(5.2, 0.5 * max(1, len(lanes)) + 2.2)
    fig, ax = plt.subplots(figsize=(15.5, fig_h), dpi=220)
    if not lanes:
        ax.set_title(title + " (no records)")
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(out_path)
        plt.close(fig)
        return

    min_start = min(float(r.start) for r in records)
    makespan = max(float(r.end) for r in records)
    if time_window is not None:
        x_min, x_max = float(time_window[0]), float(time_window[1])
    else:
        if focus_on_active_horizon:
            x_max = makespan * 1.05 if makespan > 0 else 1.0
        else:
            x_max = makespan
        margin = max(1.0, 0.02 * max(1.0, x_max - min_start))
        x_min = max(0.0, min_start - margin)
        x_max = max(x_max, makespan + margin)

    def _sparsify_events(events: List[float], max_lines: int) -> List[float]:
        ordered = sorted(set(float(x) for x in events if x_min <= float(x) <= x_max))
        if len(ordered) <= max_lines:
            return ordered
        step = max(1, len(ordered) // max_lines)
        # Keep first/last to preserve timeline anchors.
        sampled = ordered[::step]
        if ordered[-1] not in sampled:
            sampled.append(ordered[-1])
        return sorted(set(sampled))

    def _pick_color_map(job_ids: List[int]) -> Dict[int, Tuple[float, float, float, float]]:
        # Stable mapping: same job id always maps to same color in one figure.
        if len(job_ids) <= 20:
            cmap = plt.get_cmap("tab20")
            return {jid: cmap(i % 20) for i, jid in enumerate(job_ids)}
        cmap = plt.get_cmap("gist_ncar")
        n = max(2, len(job_ids))
        return {jid: cmap(i / (n - 1)) for i, jid in enumerate(job_ids)}

    lane_pos = {lane: i for i, lane in enumerate(lanes)}
    jobs = sorted({r.job_id for r in records})
    if color_by.lower() != "job":
        # Keep job coloring as the default and fallback for current workflow.
        color_by = "job"
    color_map = _pick_color_map(jobs)

    # Use latest reschedule as split point to highlight frozen prefix in final plan.
    split_t = float(frozen_split_time) if frozen_split_time is not None else (max(reschedule_times) if reschedule_times else 0.0)
    eps = 1e-9

    # Organize bars per lane to support adaptive annotation density.
    by_lane: Dict[Tuple[int, int], List[ScheduleRecord]] = {}
    for rec in records:
        by_lane.setdefault((rec.sru_id, rec.machine_id), []).append(rec)
    for lane in by_lane:
        by_lane[lane] = sorted(by_lane[lane], key=lambda r: (r.start, r.end, r.job_id, r.op_id))

    def _label_for(rec: ScheduleRecord, duration: float) -> str:
        if duration >= 1.5 * label_min_width:
            return f"J{rec.job_id}-O{rec.op_id}"
        return f"{rec.job_id}-{rec.op_id}"

    for lane in lanes:
        recs = by_lane.get(lane, [])
        y = lane_pos[lane]
        last_label_x = float("-inf")
        for idx, rec in enumerate(recs):
            st = float(rec.start)
            en = float(rec.end)
            dur = en - st
            if en < x_min or st > x_max:
                continue
            is_frozen = (st < split_t + eps) or (en <= split_t + eps)
            hatch = None
            lw = 0.55
            edge = "#1f1f1f"
            if show_frozen_hatch and not is_frozen:
                hatch = "///"
                edge = "#404040"
                lw = 0.7
            ax.barh(
                y,
                dur,
                left=st,
                color=color_map[rec.job_id],
                edgecolor=edge,
                linewidth=lw,
                height=0.76,
                hatch=hatch,
                alpha=0.93,
            )

            if not show_labels or annotate_mode == "none":
                continue
            if annotate_mode not in {"auto", "all", "sparse"}:
                continue
            if annotate_mode == "all":
                # Force label on every operation block for full traceability.
                allow_label = True
            else:
                allow_label = dur >= label_min_width
                if annotate_mode == "sparse" and (idx % 2 == 1):
                    allow_label = False
                if annotate_mode == "auto":
                    min_gap = max(4.0, 0.18 * label_min_width)
                    if st < last_label_x + min_gap:
                        allow_label = False
            if not allow_label:
                continue
            if annotate_mode == "all" and dur < max(1.0, 0.45 * label_min_width):
                # Narrow bars: place label slightly outside to keep it readable.
                tx = min(x_max, en + 0.002 * max(1.0, x_max - x_min))
                if x_min <= tx <= x_max:
                    ax.text(
                        tx,
                        y,
                        _label_for(rec, dur),
                        va="center",
                        ha="left",
                        fontsize=7.2,
                        color="#111111",
                        clip_on=True,
                    )
            else:
                cx = st + 0.5 * dur
                if not (x_min <= cx <= x_max):
                    continue
                ax.text(
                    cx,
                    y,
                    _label_for(rec, dur),
                    va="center",
                    ha="center",
                    fontsize=8.2,
                    color="#111111",
                    clip_on=True,
                )
            last_label_x = en

    if show_arrival_lines and arrival_times:
        arr = _sparsify_events(arrival_times, max_lines=max_event_lines)
        for t in arr:
            ax.axvline(x=t, color="#9f9f9f", linestyle=(0, (3, 3)), linewidth=0.7, alpha=event_line_alpha, zorder=0)
    if show_reschedule_lines and reschedule_times:
        rs = _sparsify_events(reschedule_times, max_lines=max_event_lines)
        for t in rs:
            ax.axvline(x=t, color="#d98880", linestyle=(0, (4, 4)), linewidth=0.75, alpha=event_line_alpha, zorder=0)

    # SRU structure cues on y-axis.
    separators: List[float] = []
    sru_centers: Dict[int, List[int]] = {}
    for i, lane in enumerate(lanes):
        sru_centers.setdefault(lane[0], []).append(i)
        if i > 0 and lanes[i - 1][0] != lane[0]:
            separators.append(i - 0.5)
    for y in separators:
        ax.axhline(y=y, color="#b8b8b8", linewidth=0.8, alpha=0.6)

    if split_by_sru:
        # Keep one-axis compatibility but add left-side SRU labels when splitting is requested.
        for sru_id, idxs in sru_centers.items():
            cy = 0.5 * (min(idxs) + max(idxs))
            ax.text(
                x_min - 0.02 * (x_max - x_min),
                cy,
                f"SRU{sru_id}",
                va="center",
                ha="right",
                fontsize=9.0,
                color="#333333",
            )

    ax.set_xlim(x_min, x_max)
    ax.set_yticks(range(len(lanes)))
    ax.set_yticklabels([f"SRU{s}-M{m}" for s, m in lanes], fontsize=9.8)
    ax.set_xlabel("Time", fontsize=11.0)
    ax.set_ylabel("Machine", fontsize=11.0)
    ax.set_title(title, fontsize=12.2, pad=10.0)
    ax.grid(axis="x", alpha=0.12, linestyle="--", linewidth=0.5)

    legend_items: List[object] = []
    show_jobs = jobs[: max(1, legend_max_jobs)]
    for jid in show_jobs:
        legend_items.append(Patch(facecolor=color_map[jid], edgecolor="#222222", linewidth=0.5, label=f"J{jid}"))
    if len(jobs) > len(show_jobs):
        legend_items.append(Patch(facecolor="#ffffff", edgecolor="#ffffff", label=f"... +{len(jobs) - len(show_jobs)} jobs"))
    if show_frozen_hatch:
        legend_items.append(Patch(facecolor="#f0f0f0", edgecolor="#222222", linewidth=0.5, label="frozen", hatch=None))
        legend_items.append(Patch(facecolor="#f0f0f0", edgecolor="#444444", linewidth=0.7, label="rescheduled/new", hatch="///"))
    if show_arrival_lines:
        legend_items.append(Line2D([0], [0], color="#9f9f9f", linestyle=(0, (3, 3)), linewidth=0.8, alpha=event_line_alpha, label="arrival"))
    if show_reschedule_lines:
        legend_items.append(Line2D([0], [0], color="#d98880", linestyle=(0, (4, 4)), linewidth=0.8, alpha=event_line_alpha, label="reschedule"))
    ax.legend(
        handles=legend_items,
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        borderaxespad=0.0,
        frameon=False,
        fontsize=8.2,
        ncol=1,
    )

    fig.tight_layout(rect=(0.0, 0.0, 0.82, 1.0))
    fig.savefig(out_path)
    plt.close(fig)
