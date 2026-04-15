# SM-DFJSP 复现清单（排除数据实例差异）

## 1. 范围说明
- 本清单仅评估“论文方法与代码实现的一致性”。
- 明确排除：`SDMK01-15/16-25/G01-G03` 等实例集合覆盖差异。
- 结论基于当前仓库代码与论文《Shared manufacturing-based distributed flexible job shop scheduling with supply-demand matching》对照。

## 2. 总体结论（不含实例差异）
当前代码已经完成“可运行复现框架”，但还不是“论文级同构复现”。

主要状态：
1. 主流程可跑通：已完成。
2. 论文公式/算法细节逐条同构：未完成（存在工程化简化）。
3. 统计实验框架：已补齐基础能力，但完整论文口径执行尚未完成。

---

## 3. 已完成清单

## A. 可执行框架与基础能力
1. 四层编码（UA/OS/OP/MS）已实现并可解码调度。
2. EDA-TS 主体已实现：PMA/PMS/PMM、三邻域、禁忌搜索、非支配池。
3. 对比算法入口已具备：EDA、NSGA-II、EDA-VNS、H-GA-TS。
4. 指标已实现：GD、IGD、C-metric、ODS。
5. 结果记录能力已增强：
- 支持重复运行（`n_runs`）
- 记录 run-level 与 summary-level CSV
- 写出 `run_meta.json`（环境/配置元信息）
6. Wilcoxon signed-rank 检验能力已新增（脚本级可调用）。

## B. 本轮 mk01-15 执行能力
1. 新增 `mk01-15` 一键执行脚本：`scripts/repro_mk01_15.py`（quick/full）。
2. 新增数据校验脚本：`scripts/validate_sdmk_dataset.py`。
3. 新增重复实验脚本：
- `scripts/run_experiments_repeated.py`
- `scripts/run_ablation_repeated.py`
4. Taguchi 脚本已参数化：
- 支持 `--runs-per-combo`
- 支持 `--time-limit`
- 支持 `--max-iter`

## C. 工程稳定性改进
1. `manifest.csv` 的 `file` 字段改为相对路径，避免跨机器路径污染。

---

## 4. 未完成清单（除实例差异外）

## A. 数学模型同构性未闭环
1. 论文 Eq.(1)-(16) 尚未形成逐式同名映射文档与自动核验。
2. 当前 Gurobi 模型为可解工程版，不是论文变量体系的逐项同构实现（如 `G_nx/H_rx/Q_ijrm` 的显式语义映射未闭环）。

## B. 算法细节同构仍有偏差
1. EDA 采样与辅助矩阵流程（SPA/SPS/SPM）为工程等价实现，不是论文伪代码逐行复刻。
2. TS 记忆机制存在简化：
- Tabu 键定义简化；
- LMLS/LMLM 惩罚触发逻辑与论文描述不完全一致。
3. 对比算法实现是“可比较版本”，非“文献原算法逐细节复刻”：
- EDA-VNS 以配置裁剪方式实现；
- H-GA-TS/NSGA-II 的算子与修复策略为统一工程实现，不保证与原文细节完全一致。

## C. 统计与论文表格映射未完全自动化
1. 已有 Wilcoxon 计算，但尚未自动生成论文 Table 9/10/13 的最终排版版式。
2. 尚缺“一键导出论文表格（Table 5/7/8/11/12/13）”的固定脚本与模板。

## D. 结果可信性增强项未完成
1. 未形成“公式级单元测试 + 算法行为回归测试”体系。
2. Wilcoxon 当前为正态近似实现，未提供 exact 版本切换与差异评估。

---

## 5. 与论文不一致点（排除实例差异）摘要
1. **模型层面不一致**：
- 目标函数一致，但约束实现是工程化 MILP，不是论文式变量-约束逐式同构。
2. **算法层面不一致**：
- EDA-TS 主框架一致，但部分机制（概率采样细节、Tabu/长期记忆细节）不完全同构。
3. **基线层面不一致**：
- 对比算法是“统一编码框架下的实现”，与原文引用算法细节仍有距离。
4. **统计产物层面不一致**：
- 已能算指标与显著性，但论文最终表格口径的自动汇编与版式仍未完全闭环。

---

## 6. 下一步怎么做（详细执行方案）

## 阶段 S1：先做“同构映射文档+测试”闭环（优先级最高）
目标：把“实现了”变成“可证明与论文一致/不一致”。

执行：
1. 新增 `docs/MODEL_EQ_MAPPING.md`
- 列出 Eq.(1)-(16) -> 代码文件/函数/变量/约束位置。
2. 新增测试 `tests/test_model_constraints.py`
- 对每类约束构造最小反例与正例。
3. 新增 `docs/ALGO_MAPPING.md`
- PMA/PMS/PMM、三邻域、Tabu、记忆池逐条对照论文段落。

验收：
- 每条论文公式在文档里有唯一映射与状态（同构/近似/未实现）。

## 阶段 S2：收敛算法偏差（EDA-TS 与对比算法）
目标：减少“工程近似”。

执行：
1. 细化 TS 记忆策略：
- 按论文定义重构 Tabu 对象和更新逻辑；
- 分离短期禁忌与长期惩罚触发条件。
2. 细化 PMA/PMS/PMM 采样：
- 显式实现累计概率矩阵及采样步骤，便于与论文伪代码对拍。
3. 为 EDA-VNS、H-GA-TS 增加“文献参数+算子说明”配置注释与开关。

验收：
- 同一实例下，改造前后趋势稳定，且映射文档中“近似项”数量下降。

## 阶段 S3：统计与表格自动化闭环
目标：生成论文口径表格，不靠手工。

执行：
1. 新增 `scripts/build_paper_tables.py`
- 输入：`metrics_runs.csv`、`metrics_summary.csv`、`wilcoxon.csv`、`ablation_*.csv`
- 输出：`table7.csv/table8.csv/table11.csv/table12.csv/table13.csv`
2. 新增 `scripts/build_paper_figures.py`
- 固定图命名与目录结构，映射论文图号。
3. 为 Wilcoxon 增加 `--method exact|normal`（样本量小可用 exact）。

验收：
- `reports/repro/tables` 和 `reports/repro/figures` 可一键重建。

## 阶段 S4：执行 full 级验证（mk01-15 口径）
目标：完成“当前范围内可交付复现”。

执行命令：
```powershell
$env:PYTHONPATH='src'
python scripts/repro_mk01_15.py --mode full
```

产物：
- 对比：`reports/repro/compare_01_15/*`
- 消融：`reports/repro/ablation_01_15/*`
- Taguchi：`reports/repro/taguchi_01_15/*`

验收：
- 30 次重复结果完整；
- Wilcoxon 输出完整；
- 复现报告可解释偏差来源。

---

## 7. 当前建议（立刻可做）
1. 先执行 S1（映射文档+测试），这是后续所有“是否一致”结论的依据。
2. 然后执行 S3（表格自动化），把复现产物固定下来。
3. 最后跑 `--mode full`，生成当前范围（mk01-15）的正式报告。

