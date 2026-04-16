from __future__ import annotations

# Main EDA-TS implementation:
# 1) Build probabilistic models for UA/OS/MS.
# 2) Sample population from those models.
# 3) Update models from elites + ND memory.
# 4) Intensify with tabu-search neighborhoods.
# 5) Keep next generation via NSGA-II style selection.

import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from smdfjsp.core.encoding import (
    build_compatible_sru_map,
    build_option_index,
    build_random_individual,
    op_from_ua_os,
    random_ua,
    repair_individual,
)
from smdfjsp.core.pareto import crowding_distance, dominates, fast_non_dominated_sort, merge_non_dominated
from smdfjsp.core.random_utils import RNGPack, make_rng
from smdfjsp.core.types import DecodeContext, EncodedIndividual, ObjPair, SMDFJSPInstance
from smdfjsp.model.evaluator import evaluate_individual


@dataclass
class EDATSConfig:
    # Population size per generation.
    popsize: int = 50
    # Max generation count.
    max_iter: int = 100
    # Global wall-clock time limit for one run.
    time_limit_s: float = 100.0
    # Learning rate for PMA (UA model).
    alpha: float = 0.5  # PMA lr
    # Learning rate for PMS (OS model).
    beta: float = 0.5  # PMS lr
    # Learning rate for PMM (MS model).
    gamma: float = 0.5  # PMM lr
    # Elite ratio in each generation.
    mu: float = 0.1  # elite rate
    # Penalty factor in tabu evaluation.
    epsilon: float = 0.008  # penalty factor
    # Number of TS starts (or max TS rounds).
    tmax: int = 10  # TS starts per generation
    # Max size of ND memory pool.
    nd_pool_max: int = 300
    # Random seed.
    seed: int = 42
    # Whether to mix multiple construction strategies.
    use_multi_population: bool = True
    # Whether to maintain ND memory across generations.
    use_nd_memory: bool = True
    # Whether to run tabu search intensification.
    use_ts: bool = True


@dataclass
class RunResult:
    nd_solutions: List[EncodedIndividual]
    history: List[Dict[str, float]]


class EDATS:
    def __init__(self, instance: SMDFJSPInstance, config: EDATSConfig):
        # Problem instance and run configuration.
        self.instance = instance
        self.cfg = config
        # Unified RNG pack (python + numpy RNG).
        self.rng: RNGPack = make_rng(config.seed)
        # Fast lookup: (job, op, sru) -> machine map.
        self.option_index = build_option_index(instance)
        # Cached maps to avoid repeated reconstruction.
        self.job_map = instance.job_map()
        self.sru_map = instance.sru_map()
        self.jobs_by_type = instance.jobs_by_type()
        self.srus_by_type = instance.srus_by_type()
        # Job-wise compatible SRU set (all ops feasible on that SRU).
        self.compatible_srus = build_compatible_sru_map(instance, self.option_index)
        # Initialize PMA/PMS/PMM.
        self._init_probability_matrices()

    def _init_probability_matrices(self) -> None:
        # PMA[x][job_id] -> probabilities over compatible sru ids for this job
        self.pma: Dict[int, Dict[int, np.ndarray]] = {}
        self.pma_srus: Dict[int, List[int]] = {}
        for t, jobs in self.jobs_by_type.items():
            self.pma[t] = {}
            for j in jobs:
                # Candidate SRUs for this job, fallback to all same-type SRUs.
                sru_ids = list(self.compatible_srus.get(j.job_id, []))
                if not sru_ids:
                    sru_ids = [s.sru_id for s in self.srus_by_type[t]]
                self.pma_srus[j.job_id] = sru_ids
                # Start from uniform distribution.
                uniform = np.ones(len(sru_ids), dtype=float) / len(sru_ids)
                self.pma[t][j.job_id] = uniform.copy()

        # PMS[x][job_id] -> probabilities on positions in OS vector of type x
        self.pms: Dict[int, Dict[int, np.ndarray]] = {}
        self.kx: Dict[int, int] = {}
        for t, jobs in self.jobs_by_type.items():
            # kx = number of operation tokens for this type in OS vector.
            kx = sum(len(j.operations) for j in jobs)
            self.kx[t] = kx
            uniform = np.ones(kx, dtype=float) / max(kx, 1)
            self.pms[t] = {j.job_id: uniform.copy() for j in jobs}

        # PMM[(job_id, op_id, sru_id)] -> probabilities over machines
        self.pmm: Dict[Tuple[int, int, int], np.ndarray] = {}
        self.pmm_machines: Dict[Tuple[int, int, int], List[int]] = {}
        for job in self.instance.jobs:
            for op in job.operations:
                for sru_id in self.compatible_srus.get(job.job_id, []):
                    key = (job.job_id, op.op_id, sru_id)
                    if key not in self.option_index:
                        continue
                    m_dict = self.option_index[key]
                    machines = sorted(m_dict.keys())
                    self.pmm_machines[key] = machines
                    # Uniform machine prior.
                    self.pmm[key] = np.ones(len(machines), dtype=float) / len(machines)

    def _sample_ua(self) -> Dict[int, int]:
        # Sample SRU assignment for each job from PMA.
        ua: Dict[int, int] = {}
        for t, jobs in self.jobs_by_type.items():
            for j in jobs:
                sru_ids = self.pma_srus[j.job_id]
                probs = self.pma[t][j.job_id]
                ua[j.job_id] = int(self.rng.np_rng.choice(sru_ids, p=probs))
        return ua

    def _md_ua(self) -> Dict[int, int]:
        # Heuristic UA: choose the SRU with minimal transport time for each job.
        ua: Dict[int, int] = {}
        for job in self.instance.jobs:
            candidates = self.compatible_srus.get(job.job_id, [])
            if not candidates:
                candidates = [s.sru_id for s in self.srus_by_type[job.type_id]]
            best = min(candidates, key=lambda sid: self.instance.transport_time[(job.job_id, sid)])
            ua[job.job_id] = best
        return ua

    def _sample_os(self) -> Dict[int, List[int]]:
        # Sample OS token positions based on PMS distributions.
        os_layer: Dict[int, List[int]] = {}
        for t, jobs in self.jobs_by_type.items():
            kx = self.kx[t]
            # -1 means unfilled position.
            vec = [-1] * kx
            positions = list(range(kx))
            self.rng.py_rng.shuffle(positions)
            # Implement algorithm-1 style by weighted placement.
            for j in jobs:
                remain = len(j.operations)
                for _ in range(remain):
                    probs = self.pms[t][j.job_id]
                    if not positions:
                        break
                    pos_weights = np.array([probs[p] for p in positions], dtype=float)
                    if pos_weights.sum() <= 0:
                        # Fallback to random position when weights degenerate.
                        idx = self.rng.py_rng.randrange(len(positions))
                    else:
                        pos_weights = pos_weights / pos_weights.sum()
                        idx = int(self.rng.np_rng.choice(np.arange(len(positions)), p=pos_weights))
                    pos = positions.pop(idx)
                    vec[pos] = j.job_id
            # Fill any leftover by random valid token.
            missing = []
            cnt = {}
            for job_id in vec:
                if job_id != -1:
                    cnt[job_id] = cnt.get(job_id, 0) + 1
            for j in jobs:
                need = len(j.operations) - cnt.get(j.job_id, 0)
                if need > 0:
                    missing.extend([j.job_id] * need)
            self.rng.py_rng.shuffle(missing)
            miss_cursor = 0
            for i, v in enumerate(vec):
                if v == -1:
                    vec[i] = missing[miss_cursor]
                    miss_cursor += 1
            os_layer[t] = vec
        return os_layer

    def _sample_ms(self, op_layer: Dict[int, List[Tuple[int, int]]]) -> Dict[int, List[int]]:
        # Sample machine choices (MS) for each operation in OP.
        ms: Dict[int, List[int]] = {}
        for sru_id, seq in op_layer.items():
            vec: List[int] = []
            for job_id, op_id in seq:
                key = (job_id, op_id, sru_id)
                machines = self.pmm_machines.get(key)
                probs = self.pmm.get(key)
                if machines and probs is not None:
                    vec.append(int(self.rng.np_rng.choice(machines, p=probs)))
                    continue
                options = self.option_index.get(key, {})
                if options:
                    # Fallback: random feasible machine.
                    vec.append(int(self.rng.py_rng.choice(list(options.keys()))))
            ms[sru_id] = vec
        return ms

    def _mc_ms(self, op_layer: Dict[int, List[Tuple[int, int]]]) -> Dict[int, List[int]]:
        """Choose machine with minimum processing completion cost (pt * cp)."""
        ms: Dict[int, List[int]] = {}
        for sru_id, seq in op_layer.items():
            vec: List[int] = []
            for job_id, op_id in seq:
                m_dict = self.option_index[(job_id, op_id, sru_id)]
                best_machine = min(m_dict.keys(), key=lambda m: m_dict[m][0] * m_dict[m][1])
                vec.append(best_machine)
            ms[sru_id] = vec
        return ms

    def _mct_ms(self, ua: Dict[int, int], op_layer: Dict[int, List[Tuple[int, int]]]) -> Dict[int, List[int]]:
        """Greedy choose machine to minimize projected completion time."""
        ms: Dict[int, List[int]] = {}
        # Simulated readiness states while greedily assigning machines.
        machine_ready: Dict[Tuple[int, int], float] = {}
        job_ready: Dict[int, float] = {j.job_id: 0.0 for j in self.instance.jobs}
        for sru_id, seq in op_layer.items():
            vec: List[int] = []
            for job_id, op_id in seq:
                m_dict = self.option_index[(job_id, op_id, sru_id)]
                best_m = None
                best_end = float("inf")
                for m, (pt, _) in m_dict.items():
                    st = max(job_ready[job_id], machine_ready.get((sru_id, m), 0.0))
                    en = st + pt
                    if en < best_end:
                        best_end = en
                        best_m = m
                vec.append(best_m)  # type: ignore[arg-type]
                machine_ready[(sru_id, best_m)] = best_end  # type: ignore[arg-type]
                job_ready[job_id] = best_end
            ms[sru_id] = vec
        return ms

    def _build_individual(self) -> EncodedIndividual:
        # Build one candidate individual with configurable mixed strategies.
        if self.cfg.use_multi_population:
            # UA: Sampling 80%, MD 20%
            ua = self._sample_ua() if self.rng.py_rng.random() < 0.8 else self._md_ua()
            os_layer = self._sample_os()
            op = op_from_ua_os(self.instance, ua, os_layer)
            # MS: Sampling 60%, MC 20%, MCT 20%
            r = self.rng.py_rng.random()
            if r < 0.6:
                ms = self._sample_ms(op)
            elif r < 0.8:
                ms = self._mc_ms(op)
            else:
                ms = self._mct_ms(ua, op)
        else:
            ua = self._sample_ua()
            os_layer = self._sample_os()
            op = op_from_ua_os(self.instance, ua, os_layer)
            ms = self._sample_ms(op)
        ind = EncodedIndividual(ua=ua, os=os_layer, op=op, ms=ms)
        # Final guard: repair all layers to guarantee consistency.
        return repair_individual(ind, self.instance, self.option_index, self.rng)

    @staticmethod
    def _evaluate_population(
        instance: SMDFJSPInstance,
        pop: List[EncodedIndividual],
        eval_ctx: Optional[DecodeContext] = None,
    ) -> None:
        # Evaluate objective values and feasibility for each individual.
        for ind in pop:
            result = evaluate_individual(instance, ind, ctx=eval_ctx)
            ind.objectives = result.objectives
            ind.feasible = result.feasible

    def _select_elite(self, pop: List[EncodedIndividual], elite_size: int) -> List[EncodedIndividual]:
        # NSGA-II style elite extraction.
        objs = [ind.objectives for ind in pop]  # type: ignore[list-item]
        fronts = fast_non_dominated_sort(objs)  # type: ignore[arg-type]
        selected: List[EncodedIndividual] = []
        for front in fronts:
            if len(selected) + len(front) <= elite_size:
                selected.extend(pop[i] for i in front)
            else:
                distances = crowding_distance(objs, front)  # type: ignore[arg-type]
                # Prefer larger crowding distance for diversity.
                pairs = sorted(zip(front, distances), key=lambda x: x[1], reverse=True)
                for i, _ in pairs[: elite_size - len(selected)]:
                    selected.append(pop[i])
                break
        return selected

    def _update_probability_matrices(self, en: List[EncodedIndividual]) -> None:
        # Update PMA/PMS/PMM by blending old model with elite frequencies.
        # PMA
        for t, jobs in self.jobs_by_type.items():
            for j in jobs:
                sru_ids = self.pma_srus[j.job_id]
                sru_pos = {sid: i for i, sid in enumerate(sru_ids)}
                freq = np.zeros(len(sru_ids), dtype=float)
                for ind in en:
                    sid = ind.ua[j.job_id]
                    if sid in sru_pos:
                        freq[sru_pos[sid]] += 1.0
                if freq.sum() > 0:
                    freq /= freq.sum()
                # Exponential moving average update.
                self.pma[t][j.job_id] = (1.0 - self.cfg.alpha) * self.pma[t][j.job_id] + self.cfg.alpha * freq
                self.pma[t][j.job_id] /= self.pma[t][j.job_id].sum()

        # PMS
        for t, jobs in self.jobs_by_type.items():
            kx = self.kx[t]
            for j in jobs:
                freq = np.zeros(kx, dtype=float)
                for ind in en:
                    vec = ind.os[t]
                    for pos, token in enumerate(vec):
                        if token == j.job_id:
                            freq[pos] += 1.0 / len(j.operations)
                if freq.sum() > 0:
                    freq /= freq.sum()
                self.pms[t][j.job_id] = (1.0 - self.cfg.beta) * self.pms[t][j.job_id] + self.cfg.beta * freq
                if self.pms[t][j.job_id].sum() <= 0:
                    # Degenerate guard.
                    self.pms[t][j.job_id] = np.ones(kx) / kx
                else:
                    self.pms[t][j.job_id] /= self.pms[t][j.job_id].sum()

        # PMM
        for key, base in self.pmm.items():
            machines = self.pmm_machines[key]
            mpos = {m: i for i, m in enumerate(machines)}
            freq = np.zeros(len(machines), dtype=float)
            for ind in en:
                sru_id = key[2]
                seq = ind.op.get(sru_id, [])
                ms_vec = ind.ms.get(sru_id, [])
                for i, item in enumerate(seq):
                    if item == (key[0], key[1]) and i < len(ms_vec):
                        m = ms_vec[i]
                        if m in mpos:
                            freq[mpos[m]] += 1.0
            if freq.sum() > 0:
                freq /= freq.sum()
            self.pmm[key] = (1.0 - self.cfg.gamma) * base + self.cfg.gamma * freq
            if self.pmm[key].sum() <= 0:
                # Degenerate guard.
                self.pmm[key] = np.ones(len(base)) / len(base)
            else:
                self.pmm[key] /= self.pmm[key].sum()

    def _neighbor_structure_i(self, ind: EncodedIndividual) -> List[EncodedIndividual]:
        """Job re-assignment among same-type SRUs."""
        # Change UA for a few jobs, then rebuild OP/MS.
        neighbors: List[EncodedIndividual] = []
        for t, jobs in self.jobs_by_type.items():
            candidates = jobs[:]
            self.rng.py_rng.shuffle(candidates)
            take = min(5, len(candidates))
            for job in candidates[:take]:
                possible = [sid for sid in self.compatible_srus.get(job.job_id, []) if sid != ind.ua[job.job_id]]
                if not possible:
                    continue
                moved = EncodedIndividual(
                    ua=dict(ind.ua),
                    os={k: list(v) for k, v in ind.os.items()},
                    op={k: list(v) for k, v in ind.op.items()},
                    ms={k: list(v) for k, v in ind.ms.items()},
                )
                moved.ua[job.job_id] = self.rng.py_rng.choice(possible)
                moved.op = op_from_ua_os(self.instance, moved.ua, moved.os)
                moved.ms = self._sample_ms(moved.op)
                neighbors.append(repair_individual(moved, self.instance, self.option_index, self.rng))
        return neighbors

    def _neighbor_structure_ii(self, ind: EncodedIndividual) -> List[EncodedIndividual]:
        """Insert move in OS."""
        # Move one token to another position in OS.
        neighbors: List[EncodedIndividual] = []
        for t, vec in ind.os.items():
            if len(vec) < 2:
                continue
            n_try = min(5, len(vec))
            for _ in range(n_try):
                i1 = self.rng.py_rng.randrange(len(vec))
                i2 = self.rng.py_rng.randrange(len(vec))
                if i1 == i2:
                    continue
                new_vec = list(vec)
                token = new_vec.pop(i1)
                new_vec.insert(i2, token)
                moved = EncodedIndividual(
                    ua=dict(ind.ua),
                    os={k: (new_vec if k == t else list(v)) for k, v in ind.os.items()},
                    op={},
                    ms={},
                )
                moved.op = op_from_ua_os(self.instance, moved.ua, moved.os)
                moved.ms = self._sample_ms(moved.op)
                neighbors.append(repair_individual(moved, self.instance, self.option_index, self.rng))
        return neighbors

    def _neighbor_structure_iii(self, ind: EncodedIndividual) -> List[EncodedIndividual]:
        """Machine replacement in MS."""
        # Change machine assignment for one operation.
        neighbors: List[EncodedIndividual] = []
        for sru_id, seq in ind.op.items():
            if not seq:
                continue
            n_try = min(5, len(seq))
            for _ in range(n_try):
                i = self.rng.py_rng.randrange(len(seq))
                job_id, op_id = seq[i]
                options = list(self.option_index[(job_id, op_id, sru_id)].keys())
                if len(options) <= 1:
                    continue
                moved = EncodedIndividual(
                    ua=dict(ind.ua),
                    os={k: list(v) for k, v in ind.os.items()},
                    op={k: list(v) for k, v in ind.op.items()},
                    ms={k: list(v) for k, v in ind.ms.items()},
                )
                current = moved.ms[sru_id][i]
                choices = [m for m in options if m != current]
                moved.ms[sru_id][i] = self.rng.py_rng.choice(choices)
                neighbors.append(repair_individual(moved, self.instance, self.option_index, self.rng))
        return neighbors

    def _penalized(self, obj: ObjPair, freq: int) -> ObjPair:
        # Penalize frequent move patterns to diversify TS search.
        return (obj[0] + self.cfg.epsilon * obj[0] * freq, obj[1] + self.cfg.epsilon * obj[1] * freq)

    def _tabu_search(self, initial: EncodedIndividual, eval_ctx: Optional[DecodeContext] = None) -> EncodedIndividual:
        # TS starts from one seed solution and explores three neighborhoods.
        current = initial
        current_eval = evaluate_individual(self.instance, current, ctx=eval_ctx)
        current.objectives = current_eval.objectives
        best = current
        best_obj = current.objectives

        # Tabu keys + long-term move memories.
        t_list: List[Tuple] = []
        lmls: Dict[Tuple[int, int], int] = {}
        lmlm: Dict[Tuple[int, int, int], int] = {}
        t_max_len = max(5, sum(min(5, self.kx[t]) for t in self.kx))

        for _ in range(max(1, self.cfg.tmax)):
            n1 = self._neighbor_structure_i(current)
            n2 = self._neighbor_structure_ii(current)
            n3 = self._neighbor_structure_iii(current)
            neighbors = n1 + n2 + n3
            if not neighbors:
                break
            self._evaluate_population(self.instance, neighbors, eval_ctx=eval_ctx)

            scored: List[Tuple[ObjPair, EncodedIndividual]] = []
            for nb in neighbors:
                obj = nb.objectives  # type: ignore[assignment]
                # Penalty for move frequencies.
                pen = 0
                for j, sru in nb.ua.items():
                    if sru != current.ua.get(j):
                        pen += lmls.get((sru, j), 0)
                for sru_id, seq in nb.op.items():
                    ms_vec = nb.ms.get(sru_id, [])
                    for i, (j, op_id) in enumerate(seq):
                        if i < len(ms_vec):
                            pen += lmlm.get((sru_id, j, ms_vec[i]), 0)
                scored.append((self._penalized(obj, pen), nb))
            scored.sort(key=lambda x: (x[0][0], x[0][1]))
            chosen = None
            for _, cand in scored:
                # Lightweight tabu key based on first token in each type OS.
                tabu_key = tuple(cand.os[t][0] if cand.os[t] else -1 for t in sorted(cand.os))
                if tabu_key not in t_list:
                    chosen = cand
                    t_list.append(tabu_key)
                    if len(t_list) > t_max_len:
                        t_list.pop(0)
                    break
            if chosen is None:
                # Aspiration fallback: take current best scored candidate.
                chosen = scored[0][1]
            # Update frequencies.
            for j, sru in chosen.ua.items():
                if sru != current.ua.get(j):
                    lmls[(sru, j)] = lmls.get((sru, j), 0) + 1
            for sru_id, seq in chosen.op.items():
                for i, (j, _) in enumerate(seq):
                    m = chosen.ms[sru_id][i]
                    lmlm[(sru_id, j, m)] = lmlm.get((sru_id, j, m), 0) + 1

            current = chosen
            if dominates(current.objectives, best_obj):  # type: ignore[arg-type]
                best = current
                best_obj = current.objectives
        return best

    def run(self, eval_ctx: Optional[DecodeContext] = None) -> RunResult:
        # Main evolution loop.
        start = time.time()
        pop = [self._build_individual() for _ in range(self.cfg.popsize)]
        self._evaluate_population(self.instance, pop, eval_ctx=eval_ctx)
        nd_pool: List[Tuple[ObjPair, EncodedIndividual]] = []
        if self.cfg.use_nd_memory:
            nd_pool = merge_non_dominated(
                [],
                [(ind.objectives, ind) for ind in pop if ind.objectives is not None],
                max_size=self.cfg.nd_pool_max,
            )
        history: List[Dict[str, float]] = []

        for it in range(1, self.cfg.max_iter + 1):
            if (time.time() - start) >= self.cfg.time_limit_s:
                break
            # 1) Build learning set from elites (+ memory).
            elite_size = max(1, int(self.cfg.mu * self.cfg.popsize))
            elites = self._select_elite(pop, elite_size)
            en = elites + ([x[1] for x in nd_pool] if self.cfg.use_nd_memory else [])
            self._update_probability_matrices(en)

            # 2) Sample new population from updated probabilistic models.
            new_pop = [self._build_individual() for _ in range(self.cfg.popsize)]
            self._evaluate_population(self.instance, new_pop, eval_ctx=eval_ctx)

            # TS component starts Tmax times.
            if self.cfg.use_ts and nd_pool:
                for _ in range(self.cfg.tmax):
                    seed_ind = self.rng.py_rng.choice(nd_pool)[1]
                    improved = self._tabu_search(seed_ind, eval_ctx=eval_ctx)
                    ev = evaluate_individual(self.instance, improved, ctx=eval_ctx)
                    improved.objectives = ev.objectives
                    improved.feasible = ev.feasible
                    new_pop.append(improved)

            # Environmental selection back to popsize.
            all_pop = new_pop
            objs = [ind.objectives for ind in all_pop]  # type: ignore[list-item]
            fronts = fast_non_dominated_sort(objs)  # type: ignore[arg-type]
            next_pop: List[EncodedIndividual] = []
            for front in fronts:
                if len(next_pop) + len(front) <= self.cfg.popsize:
                    next_pop.extend(all_pop[i] for i in front)
                else:
                    dist = crowding_distance(objs, front)  # type: ignore[arg-type]
                    pairs = sorted(zip(front, dist), key=lambda x: x[1], reverse=True)
                    next_pop.extend(all_pop[i] for i, _ in pairs[: self.cfg.popsize - len(next_pop)])
                    break
            pop = next_pop

            # 3) Refresh ND memory pool.
            if self.cfg.use_nd_memory:
                nd_pool = merge_non_dominated(
                    nd_pool,
                    [(ind.objectives, ind) for ind in pop if ind.objectives is not None],
                    max_size=self.cfg.nd_pool_max,
                )
            else:
                nd_pool = merge_non_dominated(
                    [],
                    [(ind.objectives, ind) for ind in pop if ind.objectives is not None],
                    max_size=self.cfg.nd_pool_max,
                )
            # 4) Record history for monitoring.
            best_cost = min(ind.objectives[0] for ind in pop if ind.objectives is not None)
            best_mk = min(ind.objectives[1] for ind in pop if ind.objectives is not None)
            history.append({"iter": it, "best_cost": best_cost, "best_makespan": best_mk, "nd_size": len(nd_pool)})

        return RunResult(nd_solutions=[x[1] for x in nd_pool], history=history)
