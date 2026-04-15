# SM-DFJSP 论文-代码对比文档

## 1. 对比范围
- 论文：`基于共享制造的分布式柔性作业车间调度与供需匹配.pdf`（C&IE 189, 2024, 109950）
- 代码范围：`src/smdfjsp`、`scripts`、`configs`、`data`
- 对比维度：数学模型、EDA-TS算法、数据集构造、对比/消融实验、统计检验与图表复现

## 2. 总体结论
当前仓库已经实现了一个**可运行的SM-DFJSP复现框架**，核心组件（四层编码、PMA/PMS/PMM、三邻域TS、多种群、非支配记忆池、GD/IGD/C-metric）基本具备。

但与论文的“严格复现”相比，仍存在显著差距：
- 实验设计与统计检验未按论文流程完整落地（30次重复、Wilcoxon、25实例全量表格）
- 数据集范围未覆盖论文全部实例（仅SDMK01-15，缺SDMK16-25与G01/G02/G03实验集）
- 数学模型和对比算法实现存在工程化简化（非逐式等价）

结论：**“算法工程实现已完成大半，论文级实证复现仍未完成”。**

## 3. 逐项对比（完成状态）
状态定义：`已完成` / `部分完成` / `未完成`

| 论文要求 | 代码对应 | 状态 | 差异说明 |
|---|---|---|---|
| SM-DFJSP双目标（总成本C + 完工期MK） | `src/smdfjsp/model/evaluator.py`，`src/smdfjsp/model/gurobi_model.py` | 部分完成 | 目标已实现；但论文变量体系`A_nr,B_nkrm,G_nx,H_rx,Q_ijrm`并未逐式完整映射到同名实现。 |
| 约束Eq.(3)-(16)逐条对应 | `src/smdfjsp/model/gurobi_model.py` | 部分完成 | 已有分配、机器选择、工序时序、机器不重叠等约束；但建模是简化MILP写法，非逐条一一同构。 |
| 四层编码UA/OS/OP/MS | `src/smdfjsp/core/types.py`，`src/smdfjsp/core/encoding.py` | 已完成 | 编码结构与解码流程齐全。 |
| PMA/PMS/PMM初始化与更新(Eq.17-29) | `src/smdfjsp/eda_ts/algorithm.py` | 部分完成 | 三概率矩阵与学习率更新已实现；采样与辅助矩阵(SPA/SPS/SPM)采用等价随机实现，非论文伪代码逐行复刻。 |
| 多种群策略+调度规则(MD/MC/MCT) | `src/smdfjsp/eda_ts/algorithm.py` | 已完成 | 已实现UA 80/20、MS 60/20/20及MD/MC/MCT策略。 |
| TS三邻域（I/II/III） | `src/smdfjsp/eda_ts/algorithm.py` | 已完成 | 三邻域都已实现。 |
| 混合短/长期禁忌记忆（T list + LMLS + LMLM） | `src/smdfjsp/eda_ts/algorithm.py` | 部分完成 | 已有Tabu列表与频次惩罚，但tabu键与惩罚触发条件为工程简化，未严格等价论文描述。 |
| 非支配解记忆池（EDA与TS双向回灌） | `src/smdfjsp/eda_ts/algorithm.py` | 部分完成 | 记忆池机制存在；但迭代中EDA/TS更新时机与论文流程图不完全同构。 |
| MK1-15扩展为SDMK01-15 | `src/smdfjsp/data/mk_parser.py`，`src/smdfjsp/data/dataset_builder.py`，`scripts/build_sdmk.py` | 已完成 | 生成流程可运行，产出`data/sdmk01-15/*.json`与`manifest.csv`。 |
| SDMK扩展规则与区间来源可追溯 | `configs/dataset_spec.yaml`，`dataset_builder.py` | 部分完成 | 已固化区间与随机种子，但“区间来源文献回溯/反校验”未在代码中闭环实现。 |
| 论文5.3 Taguchi L25(5^6)参数实验 | `scripts/tune_params_taguchi.py` | 部分完成 | L25表与ODS实现有；但未按论文执行“每组合30次、每次100s”。当前是每组合1次、30s。 |
| 论文5.4 Gurobi正确性验证（G01/G02/G03） | `src/smdfjsp/model/gurobi_model.py`，`scripts/run_gurobi_small.py` | 未完成 | 有求解器接口，但缺G01/G02/G03实例构建与表5对照流程（gap统计未形成）。 |
| 论文5.5对比实验（EDA/NSGA-II/EDA-VNS/H-GA-TS） | `src/smdfjsp/baselines/*`，`scripts/run_experiments.py` | 部分完成 | 五算法入口已通；但是工程近似实现，且实验流程未达到论文统计标准。 |
| 25实例（SDMK01-25）全量实验 | `data/sdmk01-15`，`configs/experiment*.yaml` | 未完成 | 当前仅SDMK01-15；配置默认只跑1/4/5实例子集，未覆盖SDMK16-25。 |
| GD/IGD/C-metric评估 | `src/smdfjsp/metrics/performance.py` | 已完成 | 指标函数齐全。 |
| Wilcoxon signed-rank统计检验（表9/10/13） | 全仓搜索无实现 | 未完成 | 没有统计检验脚本与结果导出。 |
| 消融实验（no_m/no_n/no_mn） | `scripts/run_ablation.py` | 部分完成 | 三消融版本已实现；但未做30次重复与Wilcoxon显著性检验。 |
| 论文图表/表格复现（表7/8/11/12/13等） | `scripts/plot_results.py`，`reports/*` | 部分完成 | 可生成PF与指标图；但缺论文级统计表、显著性表与严格同口径数值。 |
| 案例研究（表14/15、图17/18） | 仓库无案例数据与脚本 | 未完成 | 未发现对应工业案例数据与复现实验代码。 |

## 4. 已完成清单（可直接复用）
1. `SMDFJSPInstance`数据结构与IO链路完整。
2. `MK -> SDMK01-15`自动构造可运行，且有配置化参数。
3. EDA-TS主流程可运行（含PMA/PMS/PMM、多种群、TS三邻域、非支配池）。
4. EDA/NSGA-II/EDA-VNS/H-GA-TS都有可执行实现入口。
5. GD/IGD/C-metric/ODS指标函数可用。
6. 一键脚本齐全（构造数据、smoke、对比、消融、作图、gurobi小规模）。

## 5. 未完成/差距最大的部分
1. **实验规模差距**：论文是25实例+大量重复实验；当前主要是1~15实例与轻量配置。
2. **统计严谨性差距**：缺Wilcoxon显著性检验与论文同口径统计表。
3. **数据覆盖差距**：缺SDMK16-25，以及G01/G02/G03验证实例与流程。
4. **算法同构差距**：EDA-VNS/H-GA-TS等为近似复现，不是文献级逐细节复刻。
5. **模型同构差距**：Gurobi建模是可解工程版，不是论文Eq.(3)-(16)逐式等价版本。

## 6. 复现完成度评估（当前）
- 算法工程实现：约 **75%**
- 数学模型同构复现：约 **55%**
- 数据与实例体系复现：约 **50%**
- 实验与统计复现：约 **35%**
- 综合论文复现度：约 **50%~60%**

## 7. 建议的下一步（按优先级）
1. 先补齐`SDMK16-25`与`G01/G02/G03`实例生成/存档流程。
2. 改造实验脚本为论文口径：每算法每实例30次独立运行，记录均值/方差与运行时间。
3. 新增Wilcoxon统计脚本，输出表9/10/13同结构CSV。
4. 对EDA-VNS、H-GA-TS做“文献参数+算子细节”逐条核对，减少近似实现偏差。
5. 将Gurobi验证扩展为表5自动对照（含gap计算与非支配覆盖关系）。
