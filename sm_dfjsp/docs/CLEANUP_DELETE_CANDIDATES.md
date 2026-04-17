# 项目清理候选清单（待确认后执行）

更新时间：2026-04-17  
当前原则：**仅保留代码 + docs + data**（不执行删除，先确认）

## 1. 清理目标与边界

保留：
- 代码：`sm_dfjsp/src`、`sm_dfjsp/scripts`、`sm_dfjsp/configs`、`sm_dfjsp/pyproject.toml`
- 文档：`sm_dfjsp/docs`
- 数据：`sm_dfjsp/data`

待清理（候选）：
- 运行产物、缓存文件、临时目录、本地 IDE 配置

## 2. 可删候选（高置信度，删后不影响功能）

### A. Python 缓存（100%可重建）
- `sm_dfjsp/**/__pycache__/`
- `sm_dfjsp/**/*.pyc`

说明：
- 这些文件由 Python 运行自动生成，删除后下次运行会重新生成。

### B. 报告目录中的临时结果（测试产物）
- `sm_dfjsp/reports/tmp_gantt_metrics/`
- `sm_dfjsp/reports/tmp_gantt_metrics_v2/`

说明：
- 这两个目录是临时验证结果（非正式实验归档）。

## 3. 可删候选（按“仅保留代码+docs+data”严格执行）

### C. 整个报告目录（若你不保留任何历史实验结果）
- `sm_dfjsp/reports/`

当前包含目录（均为运行输出）：
- `static_vs_dynamic_sdmk01a_dyn_full`
- `static_vs_dynamic_sdmk02a_dyn_full`
- `static_vs_dynamic_sdmk03a_dyn_full`
- `static_vs_dynamic_sdmk04a_dyn_full`
- `static_vs_dynamic_sdmk05a_dyn_full`
- `tmp_gantt_metrics`
- `tmp_gantt_metrics_v2`

说明：
- 全部是可再现产物（可通过脚本重新生成）。
- 如果未来要对比历史实验结果，建议先备份后删除。

## 4. 可选清理（不属于项目核心内容）

### D. 本地 IDE 配置
- `.vscode/`

说明：
- 与业务代码无关，仅影响本地编辑器体验。

## 5. 本次建议的两种执行方案

### 方案 1（保守）
仅删除缓存与临时目录：
- A + B

### 方案 2（严格，符合“只保留代码+docs+data”）
删除：
- A + C
- （可选）D

## 6. 说明

- 本文档仅列出候选，**尚未执行任何删除**。
- 你确认方案后，我会按你选的方案一次性执行并回传删除结果清单。

