# SM-DFJSP 动态订单改造执行复现文档（dauzere sdmk01a-18a）

## 1. 执行约束

- 工作目录：`sm_dfjsp`
- 数据集来源：`data/dauzere/sdmk01a.json` ~ `data/dauzere/sdmk18a.json`
- 本次按你的要求：**只修改代码，不执行实验/脚本**
- 检查方式：**静态逻辑检查（代码链路检查 + 关键一致性检查）**

---

## 2. 本次已执行内容（代码已落地）

## 2.1 核心类型层

已改文件：`src/smdfjsp/core/types.py`

已完成：

1. `Job` 新增 `release_time: float = 0.0`
2. `SMDFJSPInstance` 新增动态字段：
   - `initial_jobs`
   - `arrival_stream`
3. 新增动态调度结构：
   - `ArrivalEvent`
   - `InProgressOpRecord`
   - `DecodeContext`
   - `RollingConfig`
   - `RollingState`

结果：

- 支持“到达时间主字段 + 在制工序显式建模 + 滚动状态容器”。

---

## 2.2 数据 I/O 与一致性策略

已改文件：`src/smdfjsp/data/io.py`

已完成：

1. JSON 读写支持 `job.release_time`
2. JSON 支持可选 `initial_jobs`、`arrival_stream`
3. 新增 `build_arrival_stream_from_release_time(jobs)`
4. 新增一致性策略：
   - 读取时若 `arrival_stream` 与 `release_time` 冲突，自动以 `release_time` 重建
   - 在 `metadata` 打标 `arrival_stream_rebuilt_from_release_time`
5. 保存时统一按 `release_time` 生成 `arrival_stream`

结果：

- 满足“`release_time` 是唯一主字段；`arrival_stream` 仅辅助索引”。

---

## 2.3 编码层（剩余子问题）

已改文件：`src/smdfjsp/core/encoding.py`

已完成：

1. 新增剩余工序 token 构造：
   - `expected_remaining_os_multiset`
   - `remaining_os_multiset`
2. 新增剩余 OS 修复：
   - `repair_os_for_remaining`
3. 新增剩余 OP 构造：
   - `op_from_ua_os_remaining`
4. 新增已开工作业 UA 冻结覆盖：
   - `apply_frozen_ua_constraints`

结果：

- 支持“只重排未开始工序”所需的编码生成与修复。

---

## 2.4 评价器（冻结 + 在制不可中断）

已改文件：`src/smdfjsp/model/evaluator.py`

已完成：

1. `evaluate_individual` 扩展为：
   - `evaluate_individual(instance, individual, ctx=None)`
2. OS 合法性校验支持滚动上下文（基于剩余工序计数）
3. 解码时支持三态：
   - 已完成工序：跳过
   - 正在加工工序：跳过并占用机器到 `expected_end_time`
   - 未开始工序：参与本轮解码
4. 已开工作业 UA 冻结校验：
   - 若个体 UA 与 `frozen_ua_by_job` 冲突，直接判 infeasible
5. 读取 `release_time` 作为最早可开工约束

结果：

- 解决“仅靠 `completed_ops_by_job` 不够，需要显式处理 in-progress”的问题。

---

## 2.5 算法入口轻量透传（不改算法机理）

已改文件：

- `src/smdfjsp/baselines/common.py`
- `src/smdfjsp/eda_ts/algorithm.py`

已完成：

1. 批量评价支持可选 `eval_ctx`
2. `EDATS.run(eval_ctx=None)` 支持传入解码上下文（默认兼容旧逻辑）
3. TS 内部评价同步支持 `eval_ctx`

结果：

- 算法机理（PMA/PMS/PMM、邻域、TS、NSGA-II）未改，只增加上下文透传能力。

---

## 2.6 滚动模块（arrival + periodic）

新增文件：

- `src/smdfjsp/rolling/state.py`
- `src/smdfjsp/rolling/events.py`
- `src/smdfjsp/rolling/controller.py`
- `src/smdfjsp/rolling/__init__.py`

已完成：

1. RollingState 初始化与状态推进
2. 到达索引构建（由 `release_time` 派生）
3. 在制工序结算与冻结记录维护
4. `build_remaining_subproblem`：
   - 仅纳入 `release_time <= t` 且未完成订单
   - 已开工作业按冻结 UA 过滤可行 SRU
5. `lift_records_from_subproblem`：
   - 将剩余子问题 op_id 映射回全局 op_id
6. `RollingScheduler`：
   - 第一阶段默认触发：arrival + periodic
   - machine_idle/op_finish 保留为事件类型（默认不启用）

结果：

- 已形成可调用的滚动控制框架，满足阶段一触发策略与冻结边界。

---

## 2.7 dauzere 动态数据构建与动态实验入口

新增文件：

- `configs/dynamic_dauzere.yaml`
- `scripts/build_dynamic_dauzere.py`
- `configs/experiment_dynamic.yaml`
- `scripts/run_dynamic_experiments.py`

已完成：

1. 基于 `data/dauzere/sdmk*.json` 直接生成动态实例（不依赖 txt 重建）
2. 生成逻辑包含：
   - `initial_job_ratio`
   - `arrival_time_range`
   - `release_time_step`
3. 动态实验脚本打通：
   - 滚动控制器
   - 剩余子问题构建
   - EDA-TS 求解与回映射
   - 输出运行摘要 JSON

---

## 2.8 对外导出调整

已改文件：

- `src/smdfjsp/core/__init__.py`
- `src/smdfjsp/data/__init__.py`

已完成：

- 导出新增的动态函数与接口，便于脚本层调用。

---

## 3. 本次未执行内容（按你的要求保留）

以下均**未执行**：

1. `scripts/build_dynamic_dauzere.py` 未运行
2. `scripts/run_dynamic_experiments.py` 未运行
3. 任何 benchmark、复现实验、可视化脚本未运行
4. 单元测试未运行

说明：这是按“先修改代码但不要执行”的要求严格执行。

---

## 4. 仍未完成/后续待办

## 4.1 高优先级待办

1. 增加自动化测试文件（当前只完成代码改造，未补 tests）
2. 完整动态指标输出：
   - 重调度次数
   - 触发来源统计（arrival/periodic）
   - 平均响应延迟
3. machine_idle / op_finish 触发策略的完整实现（当前仅保留扩展接口）

## 4.2 中优先级待办

1. 多算法动态入口（目前 `run_dynamic_experiments.py` 默认 EDA-TS 单算法）
2. 更细粒度冲突诊断与日志（例如冻结冲突原因统计）

---

## 5. 静态逻辑检查结论（未执行代码）

本次进行了跨模块静态检查，重点核对以下逻辑闭环：

1. `release_time` 主导链路：
   - 类型定义 -> JSON 读写 -> arrival 索引构建 -> rolling 激活过滤
2. 在制工序链路：
   - `RollingState.in_progress_ops` -> `DecodeContext` -> evaluator 冻结占用
3. 子问题构造链路：
   - rolling 状态筛选 -> remaining subproblem -> 结果回映射
4. 兼容性链路：
   - 旧实例缺失 `release_time` 时默认 0
   - 无动态上下文时保持静态逻辑

静态结论：

- 关键数据结构与调用链已闭环。
- 代码层满足“已完成/在制/未开始”三态区分要求。
- 满足“已开工作业 UA 冻结、未来订单不入本轮编码”的规则落地。

---

## 6. 改动文件总览

已修改：

- `src/smdfjsp/core/types.py`
- `src/smdfjsp/data/io.py`
- `src/smdfjsp/core/encoding.py`
- `src/smdfjsp/model/evaluator.py`
- `src/smdfjsp/eda_ts/algorithm.py`
- `src/smdfjsp/baselines/common.py`
- `src/smdfjsp/data/dataset_builder.py`
- `src/smdfjsp/core/__init__.py`
- `src/smdfjsp/data/__init__.py`

已新增：

- `src/smdfjsp/rolling/state.py`
- `src/smdfjsp/rolling/events.py`
- `src/smdfjsp/rolling/controller.py`
- `src/smdfjsp/rolling/__init__.py`
- `scripts/build_dynamic_dauzere.py`
- `scripts/run_dynamic_experiments.py`
- `configs/dynamic_dauzere.yaml`
- `configs/experiment_dynamic.yaml`

