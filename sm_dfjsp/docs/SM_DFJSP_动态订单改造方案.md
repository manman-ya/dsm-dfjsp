# SM-DFJSP 动态订单改造方案（按最新约束修订）

## 1. 目标与范围

在不改变现有算法机理（EDA-TS / EDA / NSGA-II / EDA-VNS / H-GA-TS 搜索逻辑不变）的前提下，将系统从静态一次性调度升级为动态滚动调度：

1. 订单新增 `release_time`（到达/释放时间）。
2. 调度方式改为滚动时域 + 事件触发重调度。
3. 解码时冻结已执行部分，仅重排未执行部分。
4. 数据集改为“初始订单 + 后续动态到达订单流”。

本方案只改“输入组织、状态管理、评价上下文、滚动控制”，不改原算法的优化机理。

---

## 2. 关键业务规则（本次新增并生效）

1. 第一阶段触发机制采用混合触发：
   - 默认开启：`新订单到达触发` + `固定周期触发`。
   - 保留扩展（默认关闭）：`机器空闲触发`、`工序完成触发`。
2. SRU 分配冻结规则：
   - 已开工订单：`UA`（作业->SRU）冻结，不允许重分配。
   - 尚未开工且已到达订单 + 新到达订单：允许在同类型 SRU 集合内重分配。
3. 时间字段权威性：
   - `release_time` 是订单到达时间唯一主字段。
   - `arrival_stream` 是由 `release_time` 自动构建的辅助索引，仅用于控制器快速触发。
   - 若 `release_time` 与 `arrival_stream` 不一致，以 `release_time` 为准并重建索引。
4. 工序状态必须三分：
   - 已完成工序：移出待优化集合。
   - 正在加工工序：不可中断，完全冻结。
   - 未开始工序：仅这一类参与本轮重调度。
5. 任意时刻 `t` 构造剩余子问题时，仅纳入：
   - `release_time <= t` 且
   - 订单尚未全部完成。
   未来订单只放在 `future_jobs`，不进入本轮编码与解码。

---

## 3. 当前代码基线

当前代码是静态口径：

- `Job` 无 `release_time` 字段。文件：`src/smdfjsp/core/types.py`
- 评价器默认 `job_ready = 0`。文件：`src/smdfjsp/model/evaluator.py`
- 算法入口是一次 run 完整实例。文件：`src/smdfjsp/eda_ts/algorithm.py`、`src/smdfjsp/baselines/*.py`
- JSON 仅静态 `jobs`，无动态索引流。文件：`src/smdfjsp/data/io.py`

---

## 4. 总体设计原则

1. 算法机理不改，只改调度组织方式。
2. 默认静态兼容：无动态字段时行为与当前版本一致。
3. 先冻结再优化：重调度永远不触碰已执行和正在加工部分。
4. 单一事实源：时间到达判定只读 `release_time`。

---

## 5. 详细改造设计（按模块）

## 5.1 类型与状态层改造

文件：`src/smdfjsp/core/types.py`（或新增 `src/smdfjsp/rolling/state.py`）

### 5.1.1 Job 扩展

- `Job.release_time: float = 0.0`

### 5.1.2 新增工序执行状态结构（关键）

新增：

- `InProgressOpRecord`
  - `job_id`
  - `op_id`
  - `sru_id`
  - `machine_id`
  - `start_time`
  - `expected_end_time`

说明：`completed_ops_by_job` 只能表达“已完成到第几道工序”，无法表达“正在加工但未完成”的冻结工序，因此必须单独建模 `in_progress_ops`。

### 5.1.3 RollingState（修订后）

`RollingState` 至少包含：

- `current_time: float`
- `active_jobs: set[int]`（已到达且未完工）
- `future_jobs: set[int]`（`release_time > current_time`）
- `completed_jobs: set[int]`
- `completed_ops_by_job: dict[int, int]`
- `in_progress_ops: dict[tuple[int, int], InProgressOpRecord]`
  - 建议 key: `(job_id, op_id)`
- `frozen_ua_by_job: dict[int, int]`
  - 仅对已开工订单强制冻结
- `machine_ready: dict[(sru_id, machine_id), float]`
- `job_ready: dict[job_id, float]`
- `frozen_records: list[ScheduleRecord]`
- `arrival_stream_index: dict[float, list[int]]`
  - 由 `release_time` 自动构建，冲突时可重建

---

## 5.2 数据与 I/O 改造

文件：`src/smdfjsp/data/io.py`

1. `jobs[]` 读写 `release_time`。
2. 支持可选字段：
   - `initial_jobs`
   - `arrival_stream`（辅助索引）
3. 加载时执行一致性策略：
   - 先读全部 `jobs.release_time`
   - 自动生成/校验 `arrival_stream`
   - 若不一致：记录 warning，并以 `release_time` 重建 `arrival_stream`

---

## 5.3 事件触发与滚动控制器

新增文件：

- `src/smdfjsp/rolling/controller.py`
- `src/smdfjsp/rolling/events.py`
- `src/smdfjsp/rolling/state.py`

### 5.3.1 RollingConfig（第一阶段默认）

- `trigger_on_arrival = True`
- `trigger_on_periodic = True`
- `periodic_interval = <配置值>`
- `trigger_on_machine_idle = False`（扩展项）
- `trigger_on_op_finish = False`（扩展项）
- `reschedule_cooldown = <配置值>`

### 5.3.2 事件优先级建议

1. 到达事件（arrival）
2. 周期事件（periodic）
3. 其他扩展事件（默认关闭）

### 5.3.3 每次重调度前的状态推进

在时刻 `t`：

1. 结算 `end_time <= t` 的在制工序：
   - 从 `in_progress_ops` 移除
   - 更新 `completed_ops_by_job`
   - 写入 `frozen_records`
2. 对 `start_time < t < end_time` 的在制工序保持冻结。
3. 激活 `release_time <= t` 的未来订单：
   - 从 `future_jobs` -> `active_jobs`
4. 组装本轮可优化集合：
   - 订单级：`active_jobs - completed_jobs`
   - 工序级：仅未开始工序

---

## 5.4 解码与评价器改造

文件：`src/smdfjsp/model/evaluator.py`

### 5.4.1 DecodeContext（修订）

新增或扩展 `DecodeContext`：

- `current_time`
- `completed_ops_by_job`
- `in_progress_ops`
- `frozen_job_ready`
- `frozen_machine_ready`
- `frozen_records`
- `frozen_ua_by_job`

### 5.4.2 evaluate_individual 扩展

签名建议：

- `evaluate_individual(instance, individual, ctx=None)`

行为：

1. 无 `ctx`：保持静态旧逻辑。
2. 有 `ctx`：
   - 初始 `job_ready[j] = max(release_time[j], frozen_job_ready[j], current_time)`
   - 初始 `machine_ready = frozen_machine_ready`
   - 已完成工序不参与本轮解码
   - 正在加工工序不参与本轮解码，且占用机器直到其 `expected_end_time`
   - 仅未开始工序由当前个体的 `OS/OP/MS` 决定

---

## 5.5 编码层改造（只编排剩余且可重排部分）

文件：`src/smdfjsp/core/encoding.py`

新增建议：

- `remaining_os_multiset(instance, state, t)`
- `repair_os_for_remaining(...)`
- `op_from_ua_os_remaining(...)`

约束：

1. OS token 仅覆盖“未开始工序”。
2. `UA` 规则：
   - 已开工订单：`UA` 强制等于 `frozen_ua_by_job[j]`
   - 未开工订单：允许在同类型可行 SRU 集合重分配
3. 在制工序不进入 `OP/MS` 重排。

---

## 5.6 数据集改造：初始订单 + 动态到达流

文件：`src/smdfjsp/data/dataset_builder.py`

新增：

- `convert_mk_to_dynamic_sdmk(...)`
- `build_arrival_stream_from_release_time(jobs)`

配置：`configs/dataset_spec.yaml`

- `dynamic.enabled`
- `dynamic.initial_job_ratio`
- `dynamic.arrival_time_range`
- `dynamic.arrival_pattern`
- `dynamic.periodic_interval`

原则：

- `arrival_stream` 永远由 `release_time` 派生。
- 不允许 `arrival_stream` 成为独立事实源。

---

## 6. 文件改动清单

## 6.1 必改

1. `src/smdfjsp/core/types.py`
2. `src/smdfjsp/data/io.py`
3. `src/smdfjsp/model/evaluator.py`
4. `src/smdfjsp/core/encoding.py`

## 6.2 新增

1. `src/smdfjsp/rolling/state.py`
2. `src/smdfjsp/rolling/events.py`
3. `src/smdfjsp/rolling/controller.py`
4. `scripts/build_dynamic_sdmk.py`
5. `scripts/run_dynamic_experiments.py`
6. `configs/experiment_dynamic.yaml`

## 6.3 轻量透传改造

1. `src/smdfjsp/baselines/common.py`（支持 `ctx`）
2. `src/smdfjsp/eda_ts/algorithm.py`（可选 `eval_ctx`）
3. `src/smdfjsp/baselines/nsgaii.py`
4. `src/smdfjsp/baselines/h_gats.py`

---

## 7. 实施顺序（更新）

## 阶段 A：类型 + I/O + 动态数据

1. 落地 `release_time`。
2. 落地 `arrival_stream` 派生/校验逻辑（以 `release_time` 为准）。
3. 生成动态样例并验证静态兼容。

## 阶段 B：状态机与冻结语义

1. 引入 `in_progress_ops`。
2. evaluator 支持“完成/在制/未开始”三态。
3. 单测验证“在制不可重排”。

## 阶段 C：滚动控制器

1. 先实现 arrival + periodic 混合触发。
2. machine_idle/op_finish 仅保留扩展接口，默认关闭。
3. 打通原算法循环调用。

## 阶段 D：实验与指标

1. 新增动态实验入口。
2. 输出重调度次数、触发构成、平均响应延迟等动态指标。

---

## 8. 验收标准（补充）

1. `release_time` 权威性：到达判定只由 `release_time` 决定。
2. 在制冻结性：`in_progress_ops` 在重调度后保持机器与时间占用不变。
3. UA 冻结规则正确：已开工订单 SRU 不变，未开工订单可重分配。
4. 子问题筛选正确：`release_time > t` 的未来订单不进入本轮编码。
5. 静态回归通过：动态开关关闭时结果口径与现有版本一致。

---

## 9. 最小新增测试清单

1. `tests/test_release_time_authority.py`
   - `arrival_stream` 与 `release_time` 冲突时自动按 `release_time` 重建。
2. `tests/test_in_progress_freeze.py`
   - 在制工序不被重排，不被中断。
3. `tests/test_ua_freeze_started_jobs.py`
   - 已开工订单 UA 冻结，未开工订单可变更。
4. `tests/test_rolling_activation_filter.py`
   - `release_time <= t` 才激活；未来订单仅留在 `future_jobs`。

---

## 10. 不改内容（边界）

以下保持不变：

- EDA-TS 的 PMA/PMS/PMM 更新机理
- TS 邻域与禁忌机制
- NSGA-II 选择/交叉/变异机理
- H-GA-TS 框架机理

仅改：动态输入、状态冻结、滚动触发和子问题构造。
