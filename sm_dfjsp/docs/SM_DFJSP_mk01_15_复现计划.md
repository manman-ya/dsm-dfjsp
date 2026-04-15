# SM-DFJSP 论文复现计划（mk01-15阶段）

## 1. 文档目标与范围
- 论文：`基于共享制造的分布式柔性作业车间调度与供需匹配.pdf`（C&IE 189, 2024, 109950）。
- 目标：评估当前代码是否“完全复现论文”，并给出后续复现计划。
- 本阶段范围：按你的要求，暂时不改数据实例，先基于 `mk01-15 -> sdmk01-15` 推进复现。
- 评估日期：2026-04-12。

## 2. 总结结论
- 当前代码**不是论文的完全复现**。
- 当前状态更准确地说是：已实现可运行的 SM-DFJSP 工程复现框架，并已覆盖论文核心算法主线，但在“实例覆盖、实验口径一致性、模型逐式同构、案例研究复现”上仍有缺口。

## 3. 论文复现基准（对照锚点）
根据论文实验部分，完整复现通常应覆盖：
- 模型：双目标 `C + MK` 与约束体系（论文公式体系）。
- 算法：EDA-TS（EDA+TS）、多种群机制、非支配记忆机制、三类邻域。
- 参数：Taguchi `L25(5^6)`，在 `SDMK17` 上每组 30 次。
- 验证：Gurobi 对 `G01/G02/G03`（表 5 口径）。
- 对比：EDA / NSGA-II / EDA-VNS / H-GA-TS，25 个实例（`SDMK01-25`），GD/IGD/C-metric 与 Wilcoxon（表 7/8/9/10）。
- 消融：`EDA-TS_no_m / no_n / no_mn`，25 实例与 Wilcoxon（表 11/12/13）。

## 4. 代码复现现状（已复现 / 未复现）

### 4.1 已复现（可运行）
- 核心算法框架已具备。
- 证据：`src/smdfjsp/eda_ts/algorithm.py`
- 细项：PMA/PMS/PMM、多种群采样、三邻域 TS、非支配记忆池、时间与迭代终止。
- 四层编码与解码、可行性修复已具备。
- 证据：`src/smdfjsp/core/encoding.py`、`src/smdfjsp/core/types.py`
- 指标与统计计算链路已具备（GD/IGD/C-metric/ODS/Wilcoxon）。
- 证据：`src/smdfjsp/metrics/performance.py`、`src/smdfjsp/metrics/stat_tests.py`
- 对比/消融重复实验脚本已具备。
- 证据：`scripts/run_experiments_repeated.py`、`scripts/run_ablation_repeated.py`
- mk01-15 一键复现流程已具备（quick/full）。
- 证据：`scripts/repro_mk01_15.py`

### 4.2 部分复现（已实现但与论文口径仍有偏差）
- 模型是工程可解版本，不是论文变量-约束逐式同构实现。
- 证据：`src/smdfjsp/model/gurobi_model.py`
- Taguchi 已有 L25 与 ODS 流程，但默认入口是 `sdmk15`，非论文 `SDMK17`。
- 证据：`scripts/tune_params_taguchi.py`、`scripts/repro_mk01_15.py`
- Wilcoxon 已输出，但当前 quick 结果 `n_runs=2`，统计显著性结论不可与论文直接对齐。
- 证据：`reports/repro/compare_01_15_quick/wilcoxon.csv`、`reports/repro/ablation_01_15_quick/ablation_wilcoxon.csv`
- 对比实验停止准则当前使用固定 `time_limit_s` 配置；论文描述是按实例设置与“EDA 100 迭代耗时”相关的口径。
- 证据：`configs/repro/experiment_01_15.yaml`、`scripts/run_experiments_repeated.py`

### 4.3 未复现
- `SDMK16-25` 未落地。
- `G01/G02/G03` 未落地。
- 论文案例研究（表 14/15，图 16/17/18）未形成可复现产物。
- 证据：`data/` 目录下无上述实例；`scripts/run_gurobi_small.py` 当前仅走 `sdmk01-15`。

## 5. 数据实例差异说明（按你的要求先记录，不修改）
- 论文实例体系：`G01/G02/G03 + SDMK01-25`。
- 当前代码实例体系：`MK01-15 -> SDMK01-15`。
- 当前 `sdmk` 构造依赖配置化假设（成本、运输、SRU 机器子集、效率系数、类型分配），属于工程化生成，不等价于论文原始发布实例文件。
- 证据：`configs/dataset_spec.yaml`、`src/smdfjsp/data/dataset_builder.py`、`data/sdmk01-15/manifest.csv`
- 结论：当前阶段结果可作为 `mk01-15` 范围内复现实验基线，但不能宣称“25实例论文原口径完全一致”。

## 6. mk01-15 阶段复现计划（执行清单）

### 阶段A：基线固化与全量运行（mk01-15）
- [ ] 运行 full 口径对比实验（30次）。
- 命令：`python scripts/run_experiments_repeated.py --config configs/repro/experiment_01_15.yaml --out-dir reports/repro/compare_01_15`
- [ ] 运行 full 口径消融实验（30次）。
- 命令：`python scripts/run_ablation_repeated.py --config configs/repro/ablation_01_15.yaml --out-dir reports/repro/ablation_01_15`
- [ ] 运行 Taguchi full（mk01-15阶段先用 `sdmk15`，并在报告中标注与论文 `SDMK17` 差异）。
- 命令：`python scripts/tune_params_taguchi.py --instance sdmk15 --runs-per-combo 30 --time-limit 100 --max-iter 100 --out-dir reports/repro/taguchi_01_15`
- 交付物：`reports/repro/compare_01_15/*`、`reports/repro/ablation_01_15/*`、`reports/repro/taguchi_01_15/*`

### 阶段B：论文口径表图构建（mk01-15子口径）
- [ ] 生成表格汇总（Table 7/8/11/12/13 对应的 mk01-15 子集版本）。
- 命令：`python scripts/build_paper_tables.py --compare-dir reports/repro/compare_01_15 --ablation-dir reports/repro/ablation_01_15 --out-dir reports/repro/tables`
- [ ] 生成可视化图件（Pareto/C-metric/甘特图等）。
- 命令：`python scripts/build_paper_figures.py --compare-dir reports/repro/compare_01_15 --ablation-dir reports/repro/ablation_01_15 --out-dir reports/repro/figures`
- 交付物：`reports/repro/tables/*`、`reports/repro/figures/*`

### 阶段C：一致性审计（文档化）
- [ ] 建立“论文项 -> 代码项 -> 当前状态（一致/近似/缺失）”矩阵。
- [ ] 明确列出本阶段所有“近似实现”与其影响范围。
- [ ] 形成 mk01-15 阶段复现报告（包含实例差异说明）。
- 交付物：`docs/` 下新增阶段报告与对照矩阵文档。

## 7. mk01-15 阶段完成判定（Done）
- 已得到 `compare_01_15 / ablation_01_15 / taguchi_01_15` 三套 full 结果。
- 已产出可追溯 run 元数据（`run_meta.json`）与可复算 CSV。
- 已产出表图汇总，并标注“仅 mk01-15、非 25 实例完整版”。
- 已明确记录实例差异，不做隐式对齐声明。

## 8. mk01-15 完成后的下一步（完整论文复现）
- 补齐 `SDMK16-25` 与 `G01/G02/G03` 数据与脚本链路。
- 将 Taguchi 实验切回论文口径实例 `SDMK17`。
- 增补 Gurobi 表 5 自动对照流程。
- 完成 25 实例版本统计与案例研究复现（表 14/15，图 16/17/18）。

