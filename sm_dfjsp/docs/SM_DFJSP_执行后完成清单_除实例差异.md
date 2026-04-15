# SM-DFJSP 执行后清单（除实例差异）

更新时间：2026-04-12
范围：基于 `docs/SM_DFJSP_复现清单_除实例差异.md` 执行；数据集限定为 `data/sdmk01-15`。

## 一、已完成清单

1. SRU 机器集合异构规则改造已完成。
- 已将 SRU 机器生成从“同质全覆盖回填”改为“异构子集生成 + 作业可分配可行性保障”。
- 关键目标已满足：同类型 SRU 的机器集合不再完全相同。

2. 数据生成器与编码器联动修复已完成。
- 已修改 `src/smdfjsp/data/dataset_builder.py`：
  - 新增异构机器子集构造逻辑；
  - 增加“每个作业至少有一个可加工 SRU”的类型内可行性保障；
  - 保留全局兜底，避免极端实例无可选加工方案。
- 已修改 `src/smdfjsp/core/encoding.py`：
  - UA 初始化与修复改为“仅从该作业可加工 SRU 集合中采样”；
  - 避免异构 SRU 下随机分配到不兼容 SRU 引发异常。

3. `sdmk01-15` 数据已重新生成并通过校验。
- 执行：`python scripts/build_sdmk.py`
- 执行：`python scripts/validate_sdmk_dataset.py --out-dir reports/repro/validation_after_sru_change`
- 结果：15/15 实例 `ok=1`、`feasible_eval=1`。
- 结果：15/15 实例 `all_same_machine_set=0`（即不存在“同类型 SRU 机器集合全部相同”的实例）。

4. 基础约束测试已通过。
- 执行：`python -m unittest tests/test_model_constraints.py`
- 结果：`Ran 4 tests, OK`。

5. 文档与复现实验脚手架补齐项已保留。
- `docs/MODEL_EQ_MAPPING.md`
- `docs/ALGO_MAPPING.md`
- `scripts/build_paper_tables.py`
- `scripts/build_paper_figures.py`

## 二、未完成清单

1. 论文“公式级同构”仍未闭环。
- 当前是工程可运行实现，不等同于 Eq.(1)-(16) 的逐项同名变量级复刻与自动校核。

2. EDA-TS 与对比算法的“论文细节同构”仍未闭环。
- TS 记忆/惩罚触发、PMA/PMS/PMM 的细节仍以工程等效为主，尚未完全按论文伪代码逐条对齐。

3. 论文表格最终口径自动出图/出表尚未完成全流程验收。
- 脚本已补齐，但尚未形成一键生成 Table 7/8/11/12/13 与对应图件的最终交付版目录快照。

4. `full` 口径（30 次重复）尚未在本轮完整重跑并固化报告。
- 本轮重点完成了 SRU 规则修复与数据可行性验证。

## 三、下一步如何做（可直接执行）

1. 跑完整复现实验（mk01-15，full 口径）。
```powershell
$env:PYTHONPATH='src'
python scripts/repro_mk01_15.py --mode full
```

2. 生成论文口径表格与图件。
```powershell
$env:PYTHONPATH='src'
python scripts/build_paper_tables.py
python scripts/build_paper_figures.py
```

3. 形成最终交付清单（建议新增）。
- `docs/SM_DFJSP_最终复现交付清单.md`
- 固化以下目录：
  - `reports/repro/compare_01_15/`
  - `reports/repro/ablation_01_15/`
  - `reports/repro/taguchi_01_15/`
  - `reports/repro/tables/`
  - `reports/repro/figures/`

## 四、关键说明

1. “每个 SRU 的机器集合不完全相同”已在 `sdmk01-15` 全集验证通过。
2. 为支持该异构规则，UA 层已升级为“按作业-可加工 SRU 集合”分配；这是必要配套改造，不是额外偏离。
3. 本文档仍按“除实例差异”口径评估，不涉及论文原始 SDMK16-25/G01-G03 的结果一致性结论。
