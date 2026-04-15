# SM-DFJSP 新手代码文档（当前版本）

## 1. 这份文档能帮你什么

这份文档是给第一次接触这个项目的人写的，目标是让你：

- 10 分钟知道项目里每个目录干什么。
- 20 分钟能把数据构建、算法冒烟、Gurobi 小规模验证跑通。
- 30 分钟能读懂核心算法模块之间如何配合。
- 通过配套的“逐行注释文档”快速理解每个算法文件。

配套逐行注释文档：

- `docs/ALGORITHM_LINE_BY_LINE.md`

---

## 2. 项目在做什么

这是一个 **共享制造分布式柔性作业车间调度（SM-DFJSP）** 复现项目，核心做了 4 件事：

1. 把 MK 基准数据（`mk01~mk15`）扩展成共享制造数据（`sdmk01~sdmk15`）。
2. 用四层编码（UA/OS/OP/MS）表示排程解，并做修复。
3. 运行多目标优化算法（EDA-TS + 基线）生成非支配解集。
4. 输出指标（GD/IGD/C-metric/Wilcoxon）和图表，支持与论文对照。

---

## 3. 当前关键口径（你最先要记住）

当前数据构建已经改成你要求的新口径：

- 每个实例总 SRU 只会是 **3 或 4**。
- 不再使用旧的 `sru_per_type: [3,4]` 固定 7 SRU 方式。

配置在：`configs/dataset_spec.yaml`

```yaml
seed: 20260408
num_types: 2

total_sru:
  candidates: [3, 4]
  method: cycle_by_instance
  split_method: balanced_min1_randomized
```

含义：

- `candidates [3,4]`：总 SRU 候选值。
- `cycle_by_instance`：按实例顺序交替使用 3、4。
- `balanced_min1_randomized`：在 2 种类型下，把总 SRU 拆到两类且每类至少 1。

---

## 4. 先跑通：一套最短命令

> 以下命令在 `sm_dfjsp` 目录执行。

### 4.1 环境准备（Windows PowerShell）

```powershell
cd d:\Code\re_code\sm-dfjsp\sm_dfjsp
conda activate sm_dfjsp
$env:PYTHONPATH = "src"
```

### 4.2 构建数据

```powershell
python scripts/build_sdmk.py
```

输出：`data/sdmk01-15/*.json` + `data/sdmk01-15/manifest.csv`

### 4.3 冒烟测试（算法是否能跑）

```powershell
python scripts/run_smoke.py
```

### 4.4 Gurobi 小规模验证

```powershell
python scripts/run_gurobi_small.py --instance sdmk01 --time-limit 60
```

---

## 5. 完整运行流程（从输入到结果）

### 步骤 A：读入原始 MK 数据

- 文件：`data/mk01.txt ~ data/mk15.txt`
- 代码：`src/smdfjsp/data/mk_parser.py`
- 作用：解析作业、工序、机器候选、加工时间。

### 步骤 B：扩展成共享制造数据

- 配置：`configs/dataset_spec.yaml`
- 代码：`src/smdfjsp/data/dataset_builder.py`
- 输出：`data/sdmk01-15/sdmkXX.json`

新增字段包括：

- SRU 集合（含 type_id 与 machine_ids）
- 运输时间 `transport_time[(job,sru)]`
- 单位运输成本 `transport_cost_per_time[(job,sru)]`
- 单位加工成本 `process_cost_per_time`

### 步骤 C：算法编码与评价

- 编码：`src/smdfjsp/core/encoding.py`
- 评价器：`src/smdfjsp/model/evaluator.py`

编码层：

- UA：作业分配到哪个 SRU
- OS：每种类型内的作业出现顺序
- OP：每个 SRU 的工序执行序列
- MS：工序在 SRU 内选哪台机器

目标：

- 总成本（加工 + 运输）
- 完工期（makespan）

### 步骤 D：运行优化算法

- 主算法 EDA-TS：`src/smdfjsp/eda_ts/algorithm.py`
- 基线：`src/smdfjsp/baselines/*.py`

### 步骤 E：统计与可视化

- 指标：`src/smdfjsp/metrics/performance.py`
- 检验：`src/smdfjsp/metrics/stat_tests.py`
- 脚本：`scripts/run_experiments*.py`、`scripts/plot_results.py`

---

## 6. 用了哪些方法（白话版）

### 6.1 EDA-TS

核心思路：

1. 建立三个概率模型（分配、顺序、机器）。
2. 每代按概率采样新解。
3. 用精英解 + 非支配记忆更新概率模型。
4. 用禁忌搜索在邻域里做局部强化。
5. 用非支配排序 + 拥挤距离做保留。

### 6.2 EDA / EDA-VNS

- EDA：EDA-TS 的简化版（关闭 TS 和记忆等组件）。
- EDA-VNS：保留局部搜索思想但配置更轻。

### 6.3 NSGA-II

- 锦标赛选择
- 交叉 + 变异
- 非支配排序 + 拥挤距离环境选择

### 6.4 H-GA-TS

- GA 负责全局搜索
- TS 在每代对较好个体做局部强化

### 6.5 Gurobi 小规模精确模型

- 变量：分配、机器选择、开始结束时间
- 约束：工序先后、机器不重叠、类型匹配
- 双层目标：先成本，再完工期

---

## 7. 每个代码文件是干什么的

## 7.1 `src/smdfjsp`（核心包）

### 顶层

- `src/smdfjsp/__init__.py`：包版本。

### `core`（通用核心）

- `core/types.py`：核心数据结构定义（Job、Operation、SRU、Instance、EncodedIndividual）。
- `core/random_utils.py`：统一随机数入口（保证可复现实验）。
- `core/encoding.py`：UA/OS/OP/MS 生成与修复。
- `core/pareto.py`：支配关系、非支配排序、拥挤距离。
- `core/__init__.py`：core 对外导出。

### `data`（数据处理）

- `data/mk_parser.py`：解析 MK 文本实例。
- `data/dataset_builder.py`：构建 SDMK 实例（当前已是总 SRU=3 或 4）。
- `data/io.py`：JSON 存取。
- `data/__init__.py`：data 对外导出。

### `eda_ts`（主算法）

- `eda_ts/algorithm.py`：EDA-TS 完整实现。
- `eda_ts/__init__.py`：导出 EDATS/EDATSConfig。

### `baselines`（基线算法）

- `baselines/eda.py`：EDA、EDA-VNS。
- `baselines/nsgaii.py`：NSGA-II。
- `baselines/h_gats.py`：H-GA-TS。
- `baselines/variation.py`：交叉、变异。
- `baselines/common.py`：评价与 NSGA-II 选择公共逻辑。
- `baselines/__init__.py`：统一导出。

### `model`（模型求值/精确模型）

- `model/evaluator.py`：统一评价器（成本+完工期）。
- `model/gurobi_model.py`：Gurobi MILP。
- `model/__init__.py`：统一导出。

### `metrics`（评价指标）

- `metrics/performance.py`：GD、IGD、C-metric、ODS。
- `metrics/stat_tests.py`：Wilcoxon 符号秩检验。
- `metrics/__init__.py`：统一导出。

---

## 7.2 `scripts`（可执行入口）

- `scripts/build_sdmk.py`：一键构建 `sdmk01-15`。
- `scripts/run_smoke.py`：快速跑通。
- `scripts/run_gurobi_small.py`：Gurobi 小规模验证。
- `scripts/run_experiments.py`：单次多算法对比。
- `scripts/run_experiments_repeated.py`：重复实验 + 统计检验。
- `scripts/run_ablation.py`：单次消融。
- `scripts/run_ablation_repeated.py`：重复消融。
- `scripts/tune_params_taguchi.py`：Taguchi 参数设计。
- `scripts/validate_sdmk_dataset.py`：数据质量校验。
- `scripts/plot_results.py`：常规图。
- `scripts/visualize_repro_results.py`：论文复现实验图（含甘特图）。
- `scripts/build_paper_tables.py`：生成论文表格 CSV。
- `scripts/build_paper_figures.py`：生成论文图。
- `scripts/repro_mk01_15.py`：复现流程总调度。
- `scripts/repro_utils.py`：run_meta、配置加载、哈希等工具。

---

## 7.3 `configs`（参数配置）

- `configs/dataset_spec.yaml`：数据构建规则（最关键）。
- `configs/experiment*.yaml`：实验主配置。
- `configs/repro/*.yaml`：复现/消融的 quick/full 配置。
- `configs/repro/taguchi_01_15_full.txt`：Taguchi 参数记录文本。

---

## 8. 你最常用的 6 条命令

```powershell
# 1) 构建数据
$env:PYTHONPATH='src'; python scripts/build_sdmk.py

# 2) 校验数据
$env:PYTHONPATH='src'; python scripts/validate_sdmk_dataset.py --out-dir reports/repro/validation

# 3) 冒烟
$env:PYTHONPATH='src'; python scripts/run_smoke.py

# 4) Gurobi 小规模验证
$env:PYTHONPATH='src'; python scripts/run_gurobi_small.py --instance sdmk01 --time-limit 60

# 5) 快速复现
$env:PYTHONPATH='src'; python scripts/repro_mk01_15.py --mode quick

# 6) 画图
$env:PYTHONPATH='src'; python scripts/visualize_repro_results.py --compare-dir reports/repro/compare_01_15_quick
```

---

## 9. 小白阅读代码顺序（推荐）

建议按这个顺序看，最不容易迷路：

1. `core/types.py`（先懂对象结构）
2. `data/dataset_builder.py`（懂数据从哪里来）
3. `core/encoding.py` + `model/evaluator.py`（懂“一个解”怎么算）
4. `eda_ts/algorithm.py`（主算法）
5. `baselines/*.py`（对照算法）
6. `scripts/run_experiments_repeated.py`（完整实验入口）

---

## 10. 常见问题

### Q1：为什么 `python scripts/*.py` 找不到 `smdfjsp`？

因为没设置 `PYTHONPATH=src`。先执行：

```powershell
$env:PYTHONPATH='src'
```

### Q2：为什么 Gurobi 脚本报错？

需要安装 `gurobipy` 并配置好许可证。否则只能跑启发式算法。

### Q3：每次构建数据会变吗？

固定 `seed` 和实例顺序时可复现；改 seed 会变化。

### Q4：当前是不是总 SRU=7？

不是。现在是每实例总 SRU=3 或 4。

---

## 11. 逐行注释入口

如果你要按行号学习每个算法文件，请看：

- `docs/ALGORITHM_LINE_BY_LINE.md`

这个文档会把每个算法文件按“行号区间 -> 含义”解释，适合第一次读源码的人。
