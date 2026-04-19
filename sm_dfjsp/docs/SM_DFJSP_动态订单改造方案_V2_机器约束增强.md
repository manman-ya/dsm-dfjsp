# SM-DFJSP 动态订单改造方案 V2（机器约束增强）

## 0. 目标与原则

基于当前项目代码，将原论文静态 EDA-TS 改造成动态订单到达场景下的 rolling Dynamic EDA-TS，新增方法名统一为：`dynamic_rolling_edats`。

核心原则：

1. 优先复用现有代码，尤其复用 `src/smdfjsp/eda_ts/algorithm.py`。
2. 尽量少改核心求解器，动态机制放在外层 rolling 模块。
3. 保留原论文核心：EDA+TS、双目标（`total_cost`/`makespan`）、非支配排序、ND 记忆池、原编码/解码、原邻域结构。
4. 不破坏现有静态流程与脚本可运行性。

---

## 1. 现有代码结构分析（当前项目）

### 1.1 核心静态求解器

- `src/smdfjsp/eda_ts/algorithm.py`
- 已包含：
  - 概率模型（PMA/PMS/PMM）
  - 采样与多策略初始化
  - Tabu Search 邻域强化
  - NSGA-II 风格环境选择
  - ND memory pool
- 结论：可作为动态子问题求解器直接复用。

### 1.2 动态基础设施（已存在）

- `src/smdfjsp/core/types.py`
  - 已支持 `Job.release_time`（默认 0）
  - 已有 `RollingConfig`、`RollingState`、`DecodeContext`
- `src/smdfjsp/rolling/state.py`
  - 已有状态初始化、冻结记录维护、decode context 构造
- `src/smdfjsp/rolling/controller.py`
  - 已有子问题构造 `build_remaining_subproblem`、冻结拼接逻辑
- `src/smdfjsp/rolling/events.py`
  - 已有 arrival/periodic 触发基础
- `src/smdfjsp/model/evaluator.py`
  - 已支持 rolling decode（`DecodeContext` + 冻结部分）

### 1.3 现有实验脚本

- `scripts/run_dynamic_experiments.py`：单实例动态脚本（雏形）
- `scripts/run_static_vs_dynamic_experiments.py`：静态/动态对比脚本（已有指标汇总框架）
- 当前缺口：
  - 统一命名 `dynamic_rolling_edats`
  - 代表解多策略选择
  - 严格事件驱动推进（含在制完工事件）
  - `run_dynamic_multi_experiments.py` 多次重复入口
  - 标准动态输出文件：`metrics_dynamic.csv` / `summary_dynamic.csv` / `run_x_details.json`

---

## 2. 最小侵入式改造方案

### 2.1 总体架构

`dynamic_rolling_edats = 外层 rolling 控制器 + 子问题构造 + 复用原 EDA-TS`

不修改 EDA-TS 内核逻辑，只在 rolling 外层实现：

1. 动态订单释放
2. 重调度触发策略
3. 冻结规则
4. 子问题封装求解
5. 代表解选择
6. 事件驱动时间推进
7. 动态指标统计

### 2.2 冻结规则

- 冻结（不可变）：
  - 已完成工序
  - 正在加工工序（非抢占）
- 可重调度：
  - 尚未开始工序
  - 新到达订单

实现路径：

1. 通过 `build_remaining_subproblem(...)` 将已完成/在制移出决策空间。
2. 子问题仅包含未开始部分。
3. 子问题求解后 lift 回全局记录并与冻结前缀拼接。

### 2.3 重调度触发策略

可配置参数：

- `arrival`
- `periodic`
- `hybrid`（arrival OR periodic）

映射到 `RollingConfig`：

- `arrival` => `trigger_on_arrival=true`, `trigger_on_periodic=false`
- `periodic` => `trigger_on_arrival=false`, `trigger_on_periodic=true`
- `hybrid` => 两者均为 `true`

### 2.4 代表解选择策略

每轮先得到 ND 集，再按策略选执行解：

- `cost_then_makespan`
- `min_makespan`
- `knee`
- `random`

要求：

- 随机策略受 seed 控制，保证复现。
- `selection_cycle` 支持周期性切换（用于多轮偏好多样化）。

### 2.5 事件驱动时间推进

推进到下一个关键事件时刻：

1. 最近在制工序完成时刻
2. 最近新订单到达时刻
3. 下一个周期触发时刻
4. `until_time`

每次跳时后刷新状态，不做 `+1` 细粒度推进。

---

## 3. 机器约束增强（动态场景硬约束）

在继承静态约束基础上，动态滚动重调度必须显式满足：

### 3.1 机器资格约束

每道工序仅可分配到原实例允许的可选机器集合，动态重调度不得扩展可选域。

### 3.2 单机容量约束

任一时刻每台机器最多加工一道工序；冻结部分与新调度拼接后，整条时间轴不得重叠。

### 3.3 机器可用时间约束

在重调度时刻 `t`，机器最早可开工时间：

`max(t, 该机器最后一个冻结工序完成时刻, 该机器在制工序预计完成时刻)`

新调度中任意工序不得早于该时刻开始。

### 3.4 冻结前缀不可插队约束

每台机器的冻结前缀（已完成+在制）不可改序；新工序只能追加在冻结前缀之后。

### 3.5 工序不可中断约束

在制工序不得中断、拆分或迁移；其机器、开始时刻、完成时刻固定。

### 3.6 工序前后顺序约束

同一作业后续工序必须同时满足：

1. 前序工序已完成
2. 目标机器在该时刻可用

### 3.7 动态拼接一致性校验（每轮必做）

每轮重调度后新增校验函数，检查：

1. 是否存在机器时间重叠
2. 是否存在工序开始时间早于机器可用时间
3. 是否存在工序被分配到非法机器
4. 是否存在冻结工序顺序被破坏

若冲突：拒绝该解并报错（或回退尝试 ND 下一候选）。

---

## 4. 关键实现设计（计划）

### 4.1 动态子问题求解包装器

新增函数：

`solve_rescheduling_subproblem_with_edats(state, config, ...)`

输入：

- 当前 `RollingState`
- 当前子问题实例
- 冻结上下文（机器/作业 ready、在制、冻结记录）
- EDA-TS 配置与代表解策略

输出：

- 当前子问题 ND 集
- ND 对应调度记录
- 本轮选中代表解
- 本轮运行耗时

### 4.2 动态拼接校验器

新增函数：

`validate_dynamic_stitching(instance, state, candidate_records, trigger_time)`

失败码建议：

- `machine_overlap`
- `machine_ready_violation`
- `illegal_machine_assignment`
- `frozen_prefix_violation`
- `in_progress_changed`
- `job_precedence_violation`

### 4.3 基准方法统一

统一三种方法输出格式：

1. `static_full_information_oracle`
2. `static_no_reschedule_baseline`
3. `dynamic_rolling_edats`

### 4.4 动态指标

至少输出：

- `total_cost`
- `makespan`（全局最终完工时刻）
- `avg_response_time`（基于 job release_time）
- `avg_flow_time`（基于 job release_time）
- `reschedule_count`
- `runtime`

---

## 5. 计划修改文件清单（最小侵入）

### 5.1 新增文件

1. `src/smdfjsp/rolling/solver.py`
   - 动态子问题求解包装器
   - ND 解评估与代表解选择策略
2. `src/smdfjsp/rolling/validation.py`
   - 动态拼接一致性校验（机器约束增强）
3. `scripts/run_dynamic_multi_experiments.py`
   - 多次重复动态实验入口
   - 输出标准动态报告文件

### 5.2 修改文件

1. `src/smdfjsp/rolling/events.py`
   - 增加在制完工事件
   - 统一 next-event 选择
2. `src/smdfjsp/rolling/controller.py`
   - 采用事件驱动推进循环
   - 重调度后调用动态拼接校验器
3. `src/smdfjsp/rolling/state.py`
   - 强化 released/unreleased 集合同步
   - 补充状态刷新一致性
4. `src/smdfjsp/core/types.py`
   - 滚动统计字段扩展（保持向后兼容）
5. `src/smdfjsp/rolling/__init__.py`
   - 导出新增 solver/validation 接口
6. `scripts/run_static_vs_dynamic_experiments.py`
   - 动态方法命名统一为 `dynamic_rolling_edats`
   - 接入新策略参数与校验流程

关键理由：

- 把动态能力集中在 rolling 层，确保 `algorithm.py` 核心逻辑不被破坏。
- 通过独立 validation 模块保证机器约束可审计、可复用、可单测。

---

## 6. 新实验入口规范

脚本：`scripts/run_dynamic_multi_experiments.py`

支持参数：

- `--instance`
- `--config`
- `--n-runs`
- `--base-seed`
- `--until-time`
- `--selection-cycle`
- `--reschedule-policy`
- `--reschedule-interval`
- `--out-dir`

输出文件：

- `metrics_dynamic.csv`
- `summary_dynamic.csv`
- `run_x_details.json`

建议在 `run_x_details.json` 中附加：

- `validation_passed`
- `validation_errors`
- `reschedule_events`
- `selected_solution_trace`

---

## 7. 运行命令示例（实施后）

```bash
python scripts/run_dynamic_multi_experiments.py \
  --instance data/dauzere_dynamic/sdmk01a_dyn.json \
  --config configs/static_vs_dynamic.yaml \
  --n-runs 10 \
  --base-seed 20260408 \
  --until-time 600 \
  --selection-cycle 1 \
  --reschedule-policy hybrid \
  --reschedule-interval 20 \
  --out-dir reports/dynamic_multi_sdmk01a_dyn_full
```

```bash
python scripts/run_dynamic_multi_experiments.py \
  --instance data/dauzere_dynamic_late36_batch/sdmk01a_dyn_late36.json \
  --config configs/static_vs_dynamic_full.yaml \
  --n-runs 5 \
  --base-seed 20260408 \
  --selection-cycle 3 \
  --reschedule-policy arrival \
  --out-dir reports/compare_dauzere_late36_medium/sdmk01a_dyn_late36/dynamic_multi
```

---

## 8. 当前方案采用的冻结规则、触发机制、近似假设

### 8.1 冻结规则

- 已完成工序冻结
- 在制工序冻结（非抢占）
- 仅未开始工序进入当前轮优化

### 8.2 触发机制

- `arrival` / `periodic` / `hybrid` 可配置
- `t=0` 必做首次求解

### 8.3 近似假设

- 每一轮将“当前可调度剩余子问题”近似为静态子问题，用 EDA-TS 求解。
- 不回溯历史冻结前缀，不做全历史重排。
- 该近似符合最小侵入目标，并保留原论文核心算法结构。

---

## 9. 兼容性与不破坏承诺

1. 静态实例（无 `release_time` 字段）默认按 `0` 处理，保持兼容。
2. 原静态实验脚本和核心 `algorithm.py` 接口保持可用。
3. 动态新增能力通过新模块与外层流程注入，不改变原论文核心求解器行为。
