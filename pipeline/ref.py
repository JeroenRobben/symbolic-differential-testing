"""Reference semantics: KLEE on clang -O0 bitcode.

Each completed KLEE path yields one z3 formula R(b, o) = pi_ref(b) /\\ o = f_ref(b) over
input bytes b0..b{n_in-1} (8-bit) and outputs o0..o{n_out-1} (64-bit).
"""
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import z3

from . import build

KMAIN = r"""
#include <stdint.h>
#include "klee/klee.h"
extern uint8_t __in[N_IN];
extern uint64_t __out[];
void __test(void);
int main(void) {
  klee_make_symbolic(__in, N_IN, "in");
  __test();
  uint64_t o[N_OUT];
  klee_make_symbolic(o, sizeof o, "out");
  for (int i = 0; i < N_OUT; i++) klee_assume(o[i] == __out[i]);
  return 0;
}
"""


def in_vars(n):
    return [z3.BitVec(f"b{i}", 8) for i in range(n)]


def out_vars(n):
    return [z3.BitVec(f"o{i}", 64) for i in range(n)]


@dataclass
class RefResult:
    paths: list = field(default_factory=list)   # z3 BoolRef per completed path
    error_paths: int = 0                         # KLEE-detected errors (UB, div0, ...)
    error_kinds: list = field(default_factory=list)
    complete: bool = True                        # explored all paths within budget
    seconds: float = 0.0
    note: str = ""


def _byte_array(name, byte_exprs):
    arr = z3.K(z3.BitVecSort(32), z3.BitVecVal(0, 8))
    for i, e in enumerate(byte_exprs):
        arr = z3.Store(arr, z3.BitVecVal(i, 32), e)
    return arr


def parse_path(smt2: str, n_in, n_out):
    asserts = z3.parse_smt2_string(smt2)
    f = z3.And(*asserts) if len(asserts) else z3.BoolVal(True)
    A = z3.ArraySort(z3.BitVecSort(32), z3.BitVecSort(8))
    subs = [(z3.Const("in", A), _byte_array("in", in_vars(n_in)))]
    obytes = [z3.Extract(8 * (j % 8) + 7, 8 * (j % 8), out_vars(n_out)[j // 8]) for j in range(8 * n_out)]
    subs.append((z3.Const("out", A), _byte_array("out", obytes)))
    # no z3.simplify: it rewrites bvudiv into bvudiv_i, which is unspecified at zero
    return z3.substitute(f, *subs)


def run(src: Path, work: Path, n_in: int, n_out: int, max_time=60, extra_cflags=(), klee_args=()) -> RefResult:
    t0 = time.time()
    work.mkdir(parents=True, exist_ok=True)
    kmain = work / "kmain.c"
    kmain.write_text(KMAIN)
    cflags = ["-O0", "-Xclang", "-disable-O0-optnone", "-g0", "-emit-llvm", "-c", "-w"]
    build.run([build.CLANG_REF, *cflags, *extra_cflags, src, "-o", work / "prog.bc"])
    build.run([build.CLANG_REF, *cflags, f"-I{build.KLEE_INCLUDE}", f"-DN_IN={n_in}", f"-DN_OUT={n_out}",
               kmain, "-o", work / "kmain.bc"])
    build.run([build.LLVM_LINK_REF, work / "prog.bc", work / "kmain.bc", "-o", work / "all.bc"])
    kout = work / "kout"
    shutil.rmtree(kout, ignore_errors=True)
    cmd = [build.KLEE / "bin" / "klee", f"--output-dir={kout}", "--write-smt2s", f"--max-time={max_time}s",
           "--check-overshift", "--check-div-zero", *klee_args, work / "all.bc"]
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=max_time + 120)
    res = RefResult()
    log = p.stderr
    if "HaltTimer invoked" in log or "halting execution" in log:
        res.complete = False
    errs = {}
    for e in kout.glob("*.err"):
        m = re.match(r"(test\d+)\.(.+)\.err", e.name)
        if m:
            errs[m.group(1)] = m.group(2)
    early = {e.name.split(".")[0] for e in kout.glob("*.early")}  # states dumped at halt: not finished paths
    if early:
        res.complete = False
    res.error_paths = len(errs)
    res.error_kinds = sorted(set(errs.values()))
    for s in sorted(kout.glob("test*.smt2")):
        if s.stem in errs or s.stem in early:
            continue
        res.paths.append(parse_path(s.read_text(), n_in, n_out))
    m = re.search(r"partially completed paths = (\d+)", log)
    if m and int(m.group(1)) > 0:
        res.complete = False
    if p.returncode != 0:
        res.note = f"klee rc={p.returncode}: {log[-500:]}"
    res.seconds = time.time() - t0
    return res
