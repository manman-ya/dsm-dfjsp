# SM-DFJSP 完整复现执行文档

## 1. 文档目标
本执行文档用于将当前仓库从“可运行复现框架”推进到“论文级完整复现交付”。

对应论文：
- Shared manufacturing-based distributed flexible job shop scheduling with supply-demand matching
- Computers & Industrial Engineering 189 (2024) 109950

对应基线评估文档：
- `docs/SM_DFJSP_论文对比文档.md`

## 1.1 当前执行范围（本轮冻结）
按当前要求，本轮仅使用 `data/mk01-15` 进行验证，即：
- 仅覆盖 `SDMK01-15` 的数据、算法、指标与实验流程验证；
- 暂不执行 `SDMK16-25` 扩展；
- 暂不执行 `G01/G02/G03` 与 Gurobi 表 5 级别对照。

说明：
- 本文档仍保留完整复现路线（P0-P8），但本轮实施优先级按 `SDMK01-15` 子集执行。

## 2. 最终交付定义（Done Definition）
当以下 8 项全部满足时，判定“完整复现完成”：
1. 数据：具备 `SDMK01-25` 与 `G01/G02/G03`，并有可重复生成脚本与 manifest。
2. 模型：SM-DFJSP 数学模型（目标+约束）具备论文口径可追溯映射说明。
3. 算法：EDA-TS 与 EDA/NSGA-II/EDA-VNS/H-GA-TS 具备论文参数口径实现与可配置入口。
4. 参数实验：完成 EDA-TS `L25(5^6)`，每组合 `30` 次、每次 `100s`（SDMK17）。
5. 对比实验：完成 25 实例多算法复现实验，输出 GD/IGD/C-metric 与运行时间统计。
6. 消融实验：完成 EDA-TS / no_m / no_n / no_mn 25 实例对照。
7. 统计检验：输出 Wilcoxon signed-rank（对应论文 Table 9/10/13 结构）。
8. 报告：提交 `REPRO_REPORT.md`，逐条对应论文 Table/Figure，说明一致项与偏差归因。

## 2.1 本轮完成定义（仅 mk01-15）
当以下条件满足时，判定“本轮验证完成”：
1. 数据仅使用 `MK01-15 -> SDMK01-15`，并通过解析/评估/smoke 校验。
2. EDA-TS 与四个对比算法在 `SDMK01-15` 可稳定运行。
3. 参数实验、对比实验、消融实验全部限定在 `SDMK01-15` 范围。
4. 产出 GD/IGD/C-metric 与 Wilcoxon 统计结果（15 实例口径）。
5. 输出本轮复现报告，明确“未覆盖 SDMK16-25 与 G01/G02/G03”。

## 3. 执行总览

### 3.1 阶段划分
- P0：环境冻结与目录规范
- P1：数据体系验证（本轮仅 SDMK01-15）
- P2：模型与约束映射补全
- P3：算法同构性补强（EDA-TS 与对比算法）
- P4：参数实验复现（Taguchi）
- P5：对比实验复现（本轮 15 实例）
- P6：消融实验复现（本轮 15 实例）
- P7：统计检验与表图生成
- P8：论文对照报告与交付打包

### 3.2 推荐产物目录
- `data/sdmk01-15/`
- `configs/repro/`
- `reports/repro/`
- `reports/repro/tables/`
- `reports/repro/figures/`
- `reports/repro/logs/`
- `docs/REPRO_REPORT.md`

## 4. 分阶段执行细则

## P0 环境冻结与目录规范

### 目标
建立可重复运行基础，避免后续实验不可复现。

### 任务
1. 固定 Python 解释器、依赖版本、随机种子策略。
2. 明确输出目录命名规则（实验轮次、实例集、算法名、时间戳）。
3. 增加“运行元数据”记录：git commit、配置文件哈希、seed、机器信息。

### 命令
```powershell
$env:PYTHONPATH='src'
python -m pip install -e .
```

### 验收标准
- 同一配置重复运行，关键统计（均值）差异仅来自随机性而非环境漂移。
- 每次实验目录都包含 `run_meta.json`。

---

## P1 数据体系验证（本轮仅 SDMK01-15）

### 目标
先确保 `SDMK01-15` 数据链路稳定可复现。

### 任务
1. 在 `src/smdfjsp/data/` 扩展数据构造器：
- 保留 `MK -> SDMK01-15` 现有流程。
- 校验 `sdmk01-15` 全实例可解析、可评估、可运行。
2. 固化并复核 manifest：
- `data/sdmk01-15/manifest.csv`
3. 固化本轮数据规则配置：
- `configs/dataset_spec.yaml`（或复制为 `configs/repro/dataset_spec_sdmk_01_15.yaml`）
4. 记录规则来源与假设（区间、类型分配、SRU 组织方式）。

### 命令（示例）
```powershell
$env:PYTHONPATH='src'
python scripts/build_sdmk.py
```

### 验收标准
- 生成并验证 `sdmk01` ... `sdmk15`。
- 每个实例可被解析、求值、快速 smoke 运行。

---

## P2 模型与约束映射补全

### 目标
形成“论文公式 -> 代码实现”可审计链路。

### 任务
1. 在 `docs/` 新增模型映射文档：
- Eq.(1)-(16) 对应到变量/约束/函数（文件+行号）。
2. 补强可行性检查器：
- 类型一致性、唯一分配、工序完整、机器可行、时序合法。
3. Gurobi 模型输出关键约束启停日志，便于核验。

### 命令（示例）
```powershell
$env:PYTHONPATH='src'
python scripts/run_gurobi_small.py --instance sdmk01 --time-limit 60
```

### 验收标准
- 模型映射表完整覆盖 Eq.(1)-(16)。
- 小规模实例求解结果可复核，异常可定位到具体约束。

---

## P3 算法同构性补强

### 目标
减少“工程近似实现”和论文算法之间的偏差。

### 任务
1. EDA-TS：
- 核对 PMA/PMS/PMM 更新与采样细节（含辅助累计概率矩阵逻辑）。
- 核对 TS 的 Tabu 键、LMLS/LMLM 惩罚触发条件。
- 核对非支配记忆池在 EDA/TS 间的更新时机。
2. 对比算法：
- EDA、NSGA-II、EDA-VNS、H-GA-TS 参数与流程与论文口径一致。
3. 统一修复策略：
- 明确 infeasible repair 的统一入口与日志。

### 验收标准
- 算法配置可一键切换到论文参数。
- 每个算法输出结构统一（front、history、runtime、seed）。

---

## P4 参数实验复现（Taguchi）

### 目标
复现论文 5.3 参数寻优流程。

### 任务
1. 保留 L25 表，改造执行脚本支持：
- 每组合 `30` 次
- 每次 `100s`
- 实例固定 `SDMK17`
2. 输出：
- 组合级统计（avg_ODS、std_ODS）
- 因子水平趋势数据
- 最优参数推荐与证据

### 命令（示例）
```powershell
$env:PYTHONPATH='src'
python scripts/tune_params_taguchi.py --instance sdmk17 --trials-per-combo 30 --time-limit 100 --out reports/repro/taguchi
```

### 验收标准
- 产出 `reports/repro/taguchi/taguchi_results.csv`
- 产出因子趋势图与最优参数结论，可映射论文 Table 3/4、Fig.10。

---

## P5 对比实验复现（本轮 15 实例）

### 目标
完成论文 5.5 主结果数据。

### 任务
1. 构建论文口径配置：
- 本轮先 15 实例（`sdmk01-15`）
- 五算法参数固定（论文口径）
- 统一初始化与停止准则
2. 执行并保存：
- 每实例每算法多次运行结果
- PF 点集、GD/IGD、C-metric、运行时间

### 命令（示例）
```powershell
$env:PYTHONPATH='src'
python scripts/run_experiments.py --config configs/repro/experiment_01_15.yaml --out-dir reports/repro/compare_01_15
```

### 验收标准
- 可直接生成 Table 7/8 所需源数据。
- 支持按实例回溯原始 front 点。

---

## P6 消融实验复现（本轮 15 实例）

### 目标
完成论文 5.6 结果。

### 任务
1. 运行 `EDA-TS` / `EDA-TS_no_m` / `EDA-TS_no_n` / `EDA-TS_no_mn`。
2. 对 15 实例（`sdmk01-15`）输出平均 GD/IGD/C-metric。

### 命令（示例）
```powershell
$env:PYTHONPATH='src'
python scripts/run_ablation.py --config configs/repro/ablation_01_15.yaml --out-dir reports/repro/ablation_01_15
```

### 验收标准
- 可直接生成 Table 11/12 所需源数据。

---

## P7 统计检验与表图生成

### 目标
补齐论文级统计显著性与最终展示物。

### 任务
1. 新增统计脚本（建议）：`scripts/run_wilcoxon.py`
- 输入：多次运行结果 CSV
- 输出：Wm、p-value、win 列
- 对应：Table 9/10/13
2. 新增汇总脚本（建议）：`scripts/build_paper_tables.py`
- 生成 `table5.csv`、`table7.csv`、`table8.csv`、`table11.csv`、`table12.csv`、`table13.csv`
3. 扩展作图脚本：
- PF 对比图、C-metric 箱线图、消融图、可选甘特图

### 验收标准
- `reports/repro/tables/` 下表格齐全。
- `reports/repro/figures/` 下图件齐全。
- 表图数据可追溯到原始运行结果。

---

## P8 论文对照报告与交付打包

### 目标
交付可审查、可复跑、可解释的复现包。

### 任务
1. 生成 `docs/REPRO_REPORT.md`：
- 逐条对应论文章节、表、图
- 标注“一致/部分一致/不一致”
- 解释偏差原因（数据、算法细节、时间预算、硬件差异）
2. 生成交付清单：
- 代码版本
- 配置文件
- 数据 manifest
- 表图路径
- 复跑命令

### 验收标准
- 第三方按 runbook 可从零复跑并复现主要结论趋势。

## 5. 执行顺序与依赖关系
1. 先 P0，再 P1。
2. P2 与 P3 可并行，但必须在 P4 前完成。
3. P4 完成后冻结 EDA-TS参数，再执行 P5/P6。
4. P7 依赖 P5/P6 原始结果。
5. P8 最后执行。

## 6. 每阶段质量门禁（Go/No-Go）
- Gate-1（P1后）：实例可解、可评估、可复跑。
- Gate-2（P3后）：算法参数与流程映射通过审查。
- Gate-3（P5/P6后）：核心指标与趋势稳定，无明显异常漂移。
- Gate-4（P7后）：统计检验完整，表图与原始数据一致。

## 7. 运行与资源预算建议
- 参数实验（P4）和对比/消融实验（P5/P6）建议分批并行执行。
- 每批次固定 seed 列表并记录硬件信息，避免结果不可比。
- 为长任务增加断点续跑与中间结果落盘（实例粒度）。

## 8. 风险与应对
1. 数据规则与论文隐藏设定不一致：
- 应对：记录假设、保留生成配置、做敏感性分析。
2. 算法实现差异导致指标偏移：
- 应对：先对齐小实例行为，再放大到 25 实例。
3. 长时实验中断：
- 应对：实例级结果实时写盘+续跑机制。
4. Gurobi 许可证或求解时间不足：
- 应对：优先完成 G01/G02/G03 验证与 gap 报告。

## 9. 最终一键执行建议（目标形态）
完成改造后，推荐具备以下入口：
```powershell
$env:PYTHONPATH='src'
python scripts/repro_full.py --config configs/repro/repro_full.yaml --out reports/repro/full
```
该入口应串联：数据检查 -> 参数实验 -> 对比实验 -> 消融实验 -> Wilcoxon -> 表图导出 -> 报告模板填充。

当前已落地（mk01-15 范围）：
```powershell
$env:PYTHONPATH='src'
python scripts/repro_mk01_15.py --mode quick
python scripts/repro_mk01_15.py --mode full
```

## 10. 交付检查清单（本轮）
- [ ] 数据：`SDMK01-15`、manifest 完整
- [ ] 配置：`configs/repro/*` 完整可复跑
- [ ] 参数实验：L25 + 30x100s 完成
- [ ] 对比实验：5算法 x 15实例完成
- [ ] 消融实验：4变体 x 15实例完成
- [ ] 统计检验：Table 9/10/13 完整
- [ ] 表图文件：Table 5/7/8/11/12/13 + 关键图完整
- [ ] 报告：`docs/REPRO_REPORT.md` 完整

---

如需，我可以继续基于本执行文档，直接给你落地下一步：
- 先生成 `configs/repro/*` 与脚本参数接口改造清单；
- 再按 P1 -> P2 顺序开始提交第一批代码改造。
