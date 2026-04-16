# SM-DFJSP 静态与动态对照实验说明

## 1. 三类方法定义

本对照实验在同一实例源数据上运行三类方法：

1. `static_full_information_oracle`
- 含义：静态全信息参考。
- 设定：将同一批订单全部视为 `t=0` 可见（`release_time=0`）。
- 作用：理想参考上界/下界口径（取决于目标定义），不是在线可实现策略。

2. `static_no_reschedule_baseline`
- 含义：静态处理基线（无动态重调度）。
- 设定：仅在 `t=0` 对初始订单做一次完整排程；后续订单到达后不做全局重调度。
- 规则：后续订单采用“简单追加到最早可行时刻”的保守规则，不改变原计划主结构。
- 作用：衡量“不做动态重调度”时的效果。

3. `dynamic_rolling_method`
- 含义：动态滚动重调度方法。
- 设定：按 `release_time` 激活订单，冻结已完成/在制工序，仅对已到达未完成部分重调度。
- 触发：第一阶段为到达触发 + 固定周期触发。

---

## 2. 公平性原则

1. 同源数据：三类方法来自同一原始订单集合。
2. 可见性差异唯一：静态全信息仅在信息可见性上不同（全部 `t=0` 可见）。
3. 目标口径一致：`total_cost` 与 `makespan` 计算口径一致。
4. 参数口径一致：默认使用同一算法参数与随机种子（除非实验设计显式区分）。

---

## 3. 可复现性

1. 固定 `seed`。
2. 统一脚本入口：`scripts/run_static_vs_dynamic_experiments.py`。
3. 统一输出：
- `metrics_static_vs_dynamic.csv`
- `metrics_static_vs_dynamic.json`
- 每个方法的 `schedule_*.json`
- 每个方法的 `gantt_*.png`

建议命令：

```powershell
$env:PYTHONPATH='src'
python scripts/run_static_vs_dynamic_experiments.py --config configs/static_vs_dynamic.yaml
```

轻量可行性命令（单实例 smoke）：

```powershell
$env:PYTHONPATH='src'
python scripts/run_static_vs_dynamic_experiments.py --config configs/static_vs_dynamic_smoke.yaml
```

---

## 4. 指标口径

输出至少包含：

- `total_cost`
- `makespan`
- `avg_response_time`
- `avg_flow_time`
- `reschedule_count`
- `runtime_seconds`

其中：

- `avg_response_time = mean(first_start_time - release_time)`
- `avg_flow_time = mean(completion_time - release_time)`

---

## 5. 结果解释建议

1. `static_full_information_oracle` 是理想参考，不代表在线可执行策略。
2. 动态方法的主要对比对象应是 `static_no_reschedule_baseline`。
3. 同时报告动态方法与 oracle 的差距，用于衡量信息不完全与在线决策损失。
