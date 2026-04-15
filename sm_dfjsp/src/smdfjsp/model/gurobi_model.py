from __future__ import annotations

# Gurobi exact model (small-scale validation):
# - binary assignment variables
# - operation-machine selection variables
# - start/end timing with disjunctive no-overlap constraints
# - lexicographic objective: minimize cost first, then makespan

from dataclasses import dataclass
from itertools import combinations
from typing import Dict, List, Tuple

from smdfjsp.core.types import SMDFJSPInstance


@dataclass
class GurobiSolveResult:
    # Gurobi status code as string.
    status: str
    # Cost objective value.
    objective_cost: float
    # Makespan objective value.
    objective_makespan: float
    # Selected SRU for each job.
    assignment: Dict[int, int]


def solve_with_gurobi(instance: SMDFJSPInstance, time_limit_s: float = 3600.0) -> GurobiSolveResult:
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("gurobipy is not available. Install optional dependency [solver].") from exc

    # Cached maps; compatibility here is type-based SRU filtering.
    job_map = instance.job_map()
    sru_map = instance.sru_map()
    compatible_srus = {j.job_id: [s.sru_id for s in instance.srus_by_type()[j.type_id]] for j in instance.jobs}

    # Collect feasible machine options by operation.
    options: Dict[Tuple[int, int], List[Tuple[int, int, int, int]]] = {}
    # item: (sru_id, machine_id, ptime, pcost)
    for job in instance.jobs:
        for op in job.operations:
            options[(job.job_id, op.op_id)] = [
                (o.sru_id, o.machine_id, o.process_time, o.process_cost_per_time) for o in op.options
            ]

    # Big-M upper bound (coarse but safe for timing disjunctions).
    upper = sum(
        max(opt[2] for opt in options[(j.job_id, op.op_id)]) for j in instance.jobs for op in j.operations
    ) + max(instance.transport_time.values())
    M = float(max(upper * 2, 1))

    model = gp.Model("sm_dfjsp")
    model.setParam("OutputFlag", 0)
    model.setParam("TimeLimit", float(time_limit_s))

    # Decision variables:
    # A(j,s): job->SRU assignment
    # B(j,o,s,m): operation->(SRU,machine) selection
    # S/E: start/end time of each operation
    # F(j): finish time of last operation for job j
    A = {}
    B = {}
    S = {}
    E = {}
    F = {}
    for j in instance.jobs:
        for s in compatible_srus[j.job_id]:
            A[(j.job_id, s)] = model.addVar(vtype=GRB.BINARY, name=f"A_{j.job_id}_{s}")
        for op in j.operations:
            S[(j.job_id, op.op_id)] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"S_{j.job_id}_{op.op_id}")
            E[(j.job_id, op.op_id)] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"E_{j.job_id}_{op.op_id}")
            for s, m, pt, cp in options[(j.job_id, op.op_id)]:
                B[(j.job_id, op.op_id, s, m)] = model.addVar(
                    vtype=GRB.BINARY, name=f"B_{j.job_id}_{op.op_id}_{s}_{m}"
                )
        F[j.job_id] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"F_{j.job_id}")

    # Objective variables.
    C = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="C")
    MK = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="MK")

    # Assignment constraints: each job chooses exactly one compatible SRU.
    for j in instance.jobs:
        model.addConstr(gp.quicksum(A[(j.job_id, s)] for s in compatible_srus[j.job_id]) == 1)

    # Each operation selects exactly one machine in one compatible SRU.
    for j in instance.jobs:
        for op in j.operations:
            model.addConstr(
                gp.quicksum(B[(j.job_id, op.op_id, s, m)] for s, m, _, _ in options[(j.job_id, op.op_id)]) == 1
            )
            for s, m, _, _ in options[(j.job_id, op.op_id)]:
                model.addConstr(B[(j.job_id, op.op_id, s, m)] <= A[(j.job_id, s)])

    # Timing equations:
    # - E = S + processing_time
    # - operation precedence inside each job
    # - F >= completion time of the last operation
    for j in instance.jobs:
        for op in j.operations:
            model.addConstr(
                E[(j.job_id, op.op_id)]
                == S[(j.job_id, op.op_id)]
                + gp.quicksum(
                    pt * B[(j.job_id, op.op_id, s, m)] for s, m, pt, _ in options[(j.job_id, op.op_id)]
                )
            )
        for op_id in range(2, len(j.operations) + 1):
            model.addConstr(S[(j.job_id, op_id)] >= E[(j.job_id, op_id - 1)])
        model.addConstr(F[j.job_id] >= E[(j.job_id, len(j.operations))])

    # No-overlap on each (sru, machine) via pairwise disjunction constraints.
    operation_ids = [(j.job_id, op.op_id) for j in instance.jobs for op in j.operations]
    for s in instance.srus:
        for m in s.machine_ids:
            cands = [(j, o) for (j, o) in operation_ids if (j, o, s.sru_id, m) in B]
            for (j1, o1), (j2, o2) in combinations(cands, 2):
                y = model.addVar(vtype=GRB.BINARY, name=f"Y_{j1}_{o1}_{j2}_{o2}_{s.sru_id}_{m}")
                model.addConstr(
                    S[(j1, o1)]
                    >= E[(j2, o2)]
                    - M * (3 - B[(j1, o1, s.sru_id, m)] - B[(j2, o2, s.sru_id, m)] - y)
                )
                model.addConstr(
                    S[(j2, o2)]
                    >= E[(j1, o1)]
                    - M * (2 - B[(j1, o1, s.sru_id, m)] - B[(j2, o2, s.sru_id, m)] + y)
                )

    # Cost and makespan definitions.
    model.addConstr(
        C
        == gp.quicksum(
            pt * cp * B[(j.job_id, op.op_id, s, m)]
            for j in instance.jobs
            for op in j.operations
            for s, m, pt, cp in options[(j.job_id, op.op_id)]
        )
        + gp.quicksum(
            instance.transport_time[(j.job_id, s)] * instance.transport_cost_per_time[(j.job_id, s)] * A[(j.job_id, s)]
            for j in instance.jobs
            for s in compatible_srus[j.job_id]
        )
    )
    for j in instance.jobs:
        model.addConstr(
            MK
            >= F[j.job_id]
            + gp.quicksum(instance.transport_time[(j.job_id, s)] * A[(j.job_id, s)] for s in compatible_srus[j.job_id])
        )

    # Two-level multi-objective:
    # priority 2 -> minimize cost first
    # priority 1 -> then minimize makespan
    model.setObjectiveN(C, index=0, priority=2, weight=1.0)
    model.setObjectiveN(MK, index=1, priority=1, weight=1.0)
    model.optimize()

    status = model.Status
    if status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL):
        # No usable solution found.
        return GurobiSolveResult(status=str(status), objective_cost=float("inf"), objective_makespan=float("inf"), assignment={})

    # Decode assignment from binary A variables.
    assignment = {}
    for j in instance.jobs:
        for s in compatible_srus[j.job_id]:
            if A[(j.job_id, s)].X > 0.5:
                assignment[j.job_id] = s
                break
    return GurobiSolveResult(
        status=str(status),
        objective_cost=float(C.X),
        objective_makespan=float(MK.X),
        assignment=assignment,
    )

