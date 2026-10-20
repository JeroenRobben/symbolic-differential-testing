"""Compilation helpers shared by all stages."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
KLEE = TOOLS / "klee" / "build"
KLEE_INCLUDE = TOOLS / "klee" / "include"
CSMITH = TOOLS / "csmith" / "install"

CLANG_REF = "/usr/lib/llvm18/bin/clang"   # must match KLEE's LLVM
LLVM_LINK_REF = "/usr/lib/llvm18/bin/llvm-link"
CLANG = os.environ.get("CC_UNDER_TEST", "/usr/bin/clang")  # compiler under test
GCC = "/usr/bin/gcc"

NATIVE_MAIN = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
extern uint8_t __in[];
extern uint64_t __out[];
void __test(void);
static void one(const char *h) {
  memset(__in, 0, N_IN);
  memset(__out, 0, N_OUT * sizeof(uint64_t));
  for (size_t i = 0; i < N_IN && h[2 * i] && h[2 * i + 1]; i++) {
    unsigned b; sscanf(h + 2 * i, "%2x", &b); __in[i] = (uint8_t)b;
  }
  __test();
  for (int i = 0; i < N_OUT; i++) printf("%llu%c", (unsigned long long)__out[i], i + 1 < N_OUT ? ' ' : '\n');
}
/* usage: prog <hex input bytes>      -> one line of outputs
          prog - < lines of hex inputs -> one line of outputs per input */
int main(int argc, char **argv) {
  if (argc > 1 && strcmp(argv[1], "-") == 0) {
    char line[4096];
    while (fgets(line, sizeof line, stdin)) { one(line); fflush(stdout); }
    return 0;
  }
  one(argc > 1 ? argv[1] : "");
  return 0;
}
"""


class BuildError(Exception):
    pass


def run(cmd, timeout=120, **kw):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout, **kw)
    if p.returncode != 0:
        raise BuildError(f"{' '.join(map(str, cmd))}\n{p.stderr[-4000:]}")
    return p


def native(src: Path, out: Path, n_in: int, n_out: int, cc=CLANG, opt="-O0", extra=()):
    """Build a native executable: program compiled with (cc, opt, extra), harness main at -O0."""
    main_c = out.with_suffix(".main.c")
    main_c.write_text(NATIVE_MAIN)
    prog_o = out.with_suffix(".prog.o")
    main_o = out.with_suffix(".main.o")
    run([cc, opt, *extra, "-w", "-c", src, "-o", prog_o])
    run([GCC, "-O0", f"-DN_IN={n_in}", f"-DN_OUT={n_out}", "-c", main_c, "-o", main_o])
    run([cc, *[e for e in extra if e.startswith("-fsanitize")], prog_o, main_o, "-o", out])
    return out


def replay(exe: Path, inp: bytes, timeout=10):
    p = subprocess.run([str(exe), inp.hex()], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise BuildError(f"replay failed rc={p.returncode}: {p.stderr[-2000:]}")
    return [int(x) for x in p.stdout.split()]


def replay_many(exe: Path, inputs, timeout=60):
    """Outputs per input; a crash truncates the list (the remaining inputs get None)."""
    p = subprocess.run([str(exe), "-"], input="".join(i.hex() + "\n" for i in inputs),
                       capture_output=True, text=True, timeout=timeout)
    lines = p.stdout.splitlines()
    res = [[int(x) for x in l.split()] for l in lines[:len(inputs)]]
    return res + [None] * (len(inputs) - len(res))
