"""Compare reference and binary path formulas.

R_i(b, o) and B_j(b, o) share input bytes b. B_j's outputs are renamed to p, then
    SAT?  R_i(b, o) /\\ B_j(b, p) /\\ OR_k o_k != p_k
gives a witness input on which the two semantics disagree.
"""
import time
from dataclasses import dataclass, field

import z3

from .ref import in_vars, out_vars


@dataclass
class Mismatch:
    witness: bytes
    ref_out: list
    bin_out: list
    ref_path: int
    bin_path: int


@dataclass
class OracleResult:
    pairs: int = 0
    overlapping: int = 0        # pairs with a jointly satisfiable input region
    unknown: int = 0            # solver timeouts
    ref_covered: int = 0        # ref paths overlapping at least one bin path
    complete: bool = True       # all pairs checked within the time budget
    mismatches: list = field(default_factory=list)


def _model_bytes(m, n_in):
    return bytes((m.eval(b, model_completion=True).as_long()) for b in in_vars(n_in))


def _model_outs(m, vs):
    return [m.eval(v, model_completion=True).as_long() for v in vs]


def compare(ref_paths, bin_paths, n_in, n_out, timeout_ms=10000, max_mismatches=3, budget=120) -> OracleResult:
    res = OracleResult()
    t0 = time.time()
    os_ = out_vars(n_out)
    ps = [z3.BitVec(f"p{k}", 64) for k in range(n_out)]
    renamed = [z3.substitute(b, *zip(os_, ps)) for b in bin_paths]
    differ = z3.Or(*[o != p for o, p in zip(os_, ps)])
    for i, r in enumerate(ref_paths):
        covered = False
        for j, b in enumerate(renamed):
            if time.time() - t0 > budget:
                res.complete = False
                break
            res.pairs += 1
            s = z3.Solver()
            s.set("timeout", timeout_ms)
            s.add(r, b)
            c = s.check()
            if c == z3.unknown:
                res.unknown += 1
                continue
            if c == z3.unsat:
                continue
            res.overlapping += 1
            covered = True
            if len(res.mismatches) >= max_mismatches:
                continue
            s.add(differ)
            c = s.check()
            if c == z3.unknown:
                res.unknown += 1
            elif c == z3.sat:
                m = s.model()
                res.mismatches.append(Mismatch(_model_bytes(m, n_in), _model_outs(m, os_), _model_outs(m, ps), i, j))
        res.ref_covered += covered
    return res


def path_inputs(ref_paths, n_in, timeout_ms=10000):
    """One concrete input per reference path (the 'concrete channel')."""
    out = []
    for r in ref_paths:
        s = z3.Solver()
        s.set("timeout", timeout_ms)
        s.add(r)
        if s.check() == z3.sat:
            out.append(_model_bytes(s.model(), n_in))
    return out
