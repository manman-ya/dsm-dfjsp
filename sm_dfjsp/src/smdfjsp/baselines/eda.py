from __future__ import annotations

# EDA-family baselines are implemented by toggling EDATS modules:
# - EDA: no TS, no multi-population, no ND memory
# - EDA-VNS: TS on, but still no multi-population / ND memory

from smdfjsp.core.types import SMDFJSPInstance
from smdfjsp.eda_ts.algorithm import EDATS, EDATSConfig, RunResult


def run_eda(instance: SMDFJSPInstance, cfg: EDATSConfig) -> RunResult:
    # Clone config so caller config is untouched.
    base = EDATSConfig(**cfg.__dict__)
    # Pure EDA ablation switches.
    base.use_ts = False
    base.use_multi_population = False
    base.use_nd_memory = False
    algo = EDATS(instance, base)
    return algo.run()


def run_eda_vns(instance: SMDFJSPInstance, cfg: EDATSConfig) -> RunResult:
    # Clone config so caller config is untouched.
    base = EDATSConfig(**cfg.__dict__)
    # EDA-VNS style switches.
    base.use_ts = True
    base.use_multi_population = False
    base.use_nd_memory = False
    # Keep TS intensity moderate.
    base.tmax = max(3, cfg.tmax // 2)
    algo = EDATS(instance, base)
    return algo.run()

