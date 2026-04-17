# SM-DFJSP 当前算法实现说明

## 1. 总览
当前代码库已实现以下算法与调度方法：

1. EDA-TS（主算法）
2. EDA（消融版）
3. EDA-VNS（消融版）
4. NSGA-II（基线）
5. H-GA-TS（基线）
6. 动态滚动调度（Rolling + 子问题重优化）
7. 小规模精确模型（Gurobi）

同时提供统一的编码、评估与帕累托选择组件，供上述算法复用。

## 2. 算法与文件映射

### 2.1 EDA-TS（主算法）
- 主要文件：`src/smdfjsp/eda_ts/algorithm.py`
- 导出入口：`src/smdfjsp/eda_ts/__init__.py`
- 核心实现：
1. 使用四层编码 `UA/OS/OP/MS`，建立概率模型 `PMA/PMS/PMM`。
2. 每代采样种群并调用统一评估器计算双目标 `(total_cost, makespan)`。
3. 从精英与 ND memory 更新概率模型（指数平滑）。
4. 通过三类邻域执行禁忌搜索强化（UA 重分配、OS 插入、MS 替换）。
5. 用 NSGA-II 的非支配排序 + 拥挤距离完成环境选择。

### 2.2 EDA（消融版）
- 主要文件：`src/smdfjsp/baselines/eda.py`
- 导出入口：`src/smdfjsp/baselines/__init__.py`
- 核心实现：
1. 复用 EDA-TS 框架。
2. 关闭 `TS`、关闭 `multi_population`、关闭 `ND memory`。
3. 得到纯 EDA 版本作为对照。

### 2.3 EDA-VNS（消融版）
- 主要文件：`src/smdfjsp/baselines/eda.py`
- 核心实现：
1. 同样复用 EDA-TS 框架。
2. 保留 TS，关闭 `multi_population` 与 `ND memory`。
3. 以较温和 `tmax` 运行 TS，形成 EDA-VNS 风格基线。

### 2.4 NSGA-II（基线）
- 主要文件：`src/smdfjsp/baselines/nsgaii.py`
- 依赖模块：`src/smdfjsp/baselines/common.py`、`src/smdfjsp/baselines/variation.py`
- 核心实现：
1. 随机初始化种群。
2. 二元锦标赛选择父代（先 rank，后 crowding）。
3. 交叉与变异产生子代。
4. 合并父子代后执行 NSGA-II 环境选择。
5. 提取非支配解集作为输出。

### 2.5 H-GA-TS（基线）
- 主要文件：`src/smdfjsp/baselines/h_gats.py`
- 核心实现：
1. GA 先做全局探索（交叉 + 变异）。
2. 每代对前 10% 候选调用 TS 做局部强化。
3. 合并改进解后再做 NSGA-II 选择。
4. TS 复用了 `EDATS` 的 `_tabu_search` 机制。

### 2.6 动态滚动调度（Rolling）
- 主要文件：
1. `src/smdfjsp/rolling/controller.py`
2. `src/smdfjsp/rolling/state.py`
3. `src/smdfjsp/rolling/events.py`
- 核心实现：
1. 按 `release_time` 构建到达流，维护 `active/future/completed` 作业集合。
2. 触发策略支持 `arrival + periodic`（并预留 machine_idle/op_finish）。
3. 每次触发构造“剩余子问题”（只含已到达且未完成、且未开始的工序）。
4. 冻结已完成与在制工序，已开工作业的 `UA` 可冻结。
5. 子问题交给优化器（通常 EDATS）求解后再回填到全局时间轴。

### 2.7 小规模精确模型（Gurobi）
- 主要文件：`src/smdfjsp/model/gurobi_model.py`
- 核心实现：
1. 建立作业-SRU 指派变量、工序-机器选择变量与时间变量。
2. 加入工序先后约束与机器互斥（析取约束）。
3. 多目标分层优化：先最小化成本，再最小化完工期。
4. 主要用于小规模验证与对照，不是主实验默认求解器。

## 3. 公共核心组件

### 3.1 统一解码与目标评估
- 文件：`src/smdfjsp/model/evaluator.py`
- 功能：
1. 校验 OS token 合法性。
2. 解码 `OP/MS` 并模拟加工开始/结束时间。
3. 累加加工成本与运输成本，计算 `makespan`。
4. 支持 `DecodeContext`，可用于滚动场景（冻结前缀、在制工序、可调度子集）。

### 3.2 编码与修复
- 文件：`src/smdfjsp/core/encoding.py`
- 功能：
1. 构建可行选项索引与兼容 SRU 集。
2. 随机生成与修复 `UA/OS/OP/MS`。
3. 支持滚动模式的“剩余工序”编码与修复。
4. 支持冻结 `UA` 约束合并。

### 3.3 帕累托工具
- 文件：`src/smdfjsp/core/pareto.py`
- 功能：
1. `dominates` 支配判定。
2. `fast_non_dominated_sort` 非支配分层。
3. `crowding_distance` 拥挤距离计算。
4. ND 集合合并与截断。

## 4. 运行入口脚本

1. 多算法静态对比：`scripts/run_experiments.py`
2. 动态滚动单实例：`scripts/run_dynamic_experiments.py`
3. 静态/动态公平对比：`scripts/run_static_vs_dynamic_experiments.py`

## 5. 当前实现边界

1. 生产实验主力仍是启发式多目标框架（EDA-TS 与基线族）。
2. Gurobi 精确模型为可选依赖（安装 `gurobipy` 后可运行）。
3. 动态调度采用“滚动重优化 + 冻结已执行部分”机制，而非在线强化学习框架。
