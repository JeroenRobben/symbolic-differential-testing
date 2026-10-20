"""Compiled-code semantics: angr on the x86-64 binary built by the compiler under test.

Each completed path yields B(b, o) = pi_bin(b) /\\ o = f_bin(b), same variables as ref.py.
"""
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import z3

logging.getLogger("angr").setLevel(logging.ERROR)
logging.getLogger("cle").setLevel(logging.ERROR)
logging.getLogger("pyvex").setLevel(logging.ERROR)

import angr  # noqa: E402
from angr.rustylib import claripy  # noqa: E402

from . import build  # noqa: E402


@dataclass
class BinResult:
    paths: list = field(default_factory=list)  # z3 BoolRef per completed path
    errored: int = 0                            # angr errored states (unsupported insn, ...)
    complete: bool = True
    seconds: float = 0.0
    note: str = ""


def compile_exe(src: Path, out: Path, n_in, n_out, cc=build.CLANG, opt="-O2", extra=()):
    return build.native(src, out, n_in, n_out, cc=cc, opt=opt, extra=extra)


def run(exe: Path, n_in: int, n_out: int, max_time=60, max_paths=256) -> BinResult:
    t0 = time.time()
    res = BinResult()
    proj = angr.Project(str(exe), auto_load_libs=False)
    sym = {n: proj.loader.find_symbol(n) for n in ("__in", "__out", "__test")}
    st = proj.factory.call_state(
        sym["__test"].rebased_addr,
        add_options={angr.options.ZERO_FILL_UNCONSTRAINED_MEMORY,
                     angr.options.ZERO_FILL_UNCONSTRAINED_REGISTERS},
        remove_options={angr.options.SIMPLIFY_CONSTRAINTS} if hasattr(angr.options, "SIMPLIFY_CONSTRAINTS") else set())
    bs = [claripy.BVS(f"b{i}", 8, explicit_name=True) for i in range(n_in)]
    st.memory.store(sym["__in"].rebased_addr, claripy.Concat(*bs))  # big-endian concat: b0 at lowest address
    st.memory.store(sym["__out"].rebased_addr, claripy.BVV(0, 64 * n_out))
    sm = proj.factory.simulation_manager(st)
    while sm.active:
        if time.time() - t0 > max_time or len(sm.deadended) >= max_paths:
            res.complete = False
            break
        sm.step()
    res.errored = len(sm.errored)
    if sm.errored:
        res.complete = False
        res.note = repr(sm.errored[0].error)[:300]
    outs = [claripy.BVS(f"o{k}", 64, explicit_name=True) for k in range(n_out)]
    for s in sm.deadended:
        solver = claripy.Solver()
        for c in s.solver.constraints:
            solver.add(c)
        for k in range(n_out):
            v = s.memory.load(sym["__out"].rebased_addr + 8 * k, 8, endness="Iend_LE")
            solver.add(outs[k] == v)
        f = z3.parse_smt2_string(solver.to_smt2())
        res.paths.append(z3.And(*f) if len(f) else z3.BoolVal(True))
    res.seconds = time.time() - t0
    return res
