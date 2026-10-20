"""Native confirmation of a candidate witness.

Verdicts:
  confirmed    -- clang -O0 and gcc -O0 agree, UBSan is clean, the config under test differs
  ref-disagree -- clang -O0 and gcc -O0 disagree (UB / implementation-defined behaviour suspected)
  ub           -- UBSan fires on the witness
  ref-engine   -- natively nothing differs; KLEE's predicted outputs were wrong
  bin-engine   -- natively nothing differs; angr's predicted outputs were wrong
  engine       -- natively nothing differs; both predictions wrong / unattributable
  build-error  -- something failed to build or run
"""
from pathlib import Path

from . import build


class Natives:
    """Lazily built native executables for one program, cached per configuration."""

    def __init__(self, src: Path, work: Path, n_in, n_out):
        self.src, self.work, self.n_in, self.n_out = src, work, n_in, n_out
        self.cache = {}

    def exe(self, name, cc, opt, extra=()):
        if name not in self.cache:
            self.cache[name] = build.native(self.src, self.work / f"native-{name}", self.n_in, self.n_out,
                                            cc=cc, opt=opt, extra=extra)
        return self.cache[name]

    def ref_clang(self):
        return self.exe("clang-O0", build.CLANG, "-O0")

    def ref_gcc(self):
        return self.exe("gcc-O0", build.GCC, "-O0")

    def ubsan(self):
        return self.exe("ubsan", build.CLANG, "-O0", ("-fsanitize=undefined", "-fno-sanitize-recover=all"))


def classify(natives: Natives, dut_exe: Path, witness: bytes, ref_pred=None, bin_pred=None, dut_src_natives=None):
    """dut_src_natives: Natives for the program the DUT was built from, if it differs (seeded mutants)."""
    try:
        a = build.replay(natives.ref_clang(), witness)
        g = build.replay(natives.ref_gcc(), witness)
        if a != g:
            return "ref-disagree", {"clang_O0": a, "gcc_O0": g}
        try:
            build.replay(natives.ubsan(), witness)
        except build.BuildError as e:
            return "ub", {"ubsan": str(e)[:500]}
        d = build.replay(dut_exe, witness)
    except build.BuildError as e:
        return "build-error", {"error": str(e)[:500]}
    info = {"ref_native": a, "dut_native": d, "ref_pred": ref_pred, "bin_pred": bin_pred}
    if d != a:
        return "confirmed", info
    if ref_pred is None:
        return "agree", info
    ref_wrong = ref_pred != a
    bin_wrong = bin_pred != d
    if ref_wrong and not bin_wrong:
        return "ref-engine", info
    if bin_wrong and not ref_wrong:
        return "bin-engine", info
    return "engine", info
