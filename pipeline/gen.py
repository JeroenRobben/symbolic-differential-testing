"""Test-program generators.

Every generated program exposes the same harness interface:
    uint8_t  __in[N_IN];    -- symbolic input bytes b0..b{N_IN-1}
    uint64_t __out[N_OUT];  -- observable outputs
    void     __test(void);  -- reads __in, writes __out
The programs must be free of undefined behaviour for every input.
"""
import random
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

N_IN = 16


@dataclass
class Program:
    source: str
    n_in: int
    n_out: int
    gen: str
    seed: int


# (C type, bit width, signed)
TYPES = [
    ("int8_t", 8, True), ("uint8_t", 8, False),
    ("int16_t", 16, True), ("uint16_t", 16, False),
    ("int32_t", 32, True), ("uint32_t", 32, False),
    ("int64_t", 64, True), ("uint64_t", 64, False),
]

PRELUDE = """\
#include <stdint.h>
"""


def _utype(w):
    return f"uint{w}_t"


class ArithGen:
    """Integer-arithmetic functions with branches and bounded loops.

    Arithmetic is performed in the unsigned type of the operand width and converted back, so there is no
    signed overflow; shift amounts are masked; division guards zero and INT_MIN/-1.
    """

    def __init__(self, rng: random.Random, n_vars=6, n_stmts=10, max_depth=3):
        self.r = rng
        self.n_vars = n_vars
        self.n_stmts = n_stmts
        self.max_depth = max_depth
        self.vars = []  # (name, ctype, width, signed)

    def const(self, w, signed):
        r = self.r
        special = [0, 1, 2, 3, 7, 8, 15, 16, 31, 32, 63, 64, 127, 128, 255, (1 << (w - 1)) - 1,
                   (1 << (w - 1)), (1 << w) - 1, (1 << w) - 2]
        v = r.choice(special) if r.random() < 0.7 else r.getrandbits(w)
        v &= (1 << w) - 1
        if signed and v >= 1 << (w - 1):
            v -= 1 << w
        if signed and v == -(1 << (w - 1)):
            return f"({v + 1} - 1)" if w < 64 else "INT64_MIN"
        suffix = "" if w <= 32 else ("LL" if signed else "ULL")
        return f"{v}{suffix}" if signed else f"{v}U{'LL' if w > 32 else ''}"

    def var(self, want=None):
        cands = [v for v in self.vars if want is None or (v[2], v[3]) == want]
        return self.r.choice(cands) if cands else None

    def leaf(self, w, signed):
        v = self.var()
        if v is None or self.r.random() < 0.25:
            return self.const(w, signed)
        name, ctype, vw, vs = v
        return f"(({ 'int' if signed else 'uint' }{w}_t){name})"

    def expr(self, w, signed, depth=0):
        r = self.r
        t = f"{'int' if signed else 'uint'}{w}_t"
        u = _utype(w)
        # cast that avoids promotion to (signed) int for narrow types
        uc = f"(uint32_t)({u})" if w < 32 else f"({u})"
        if depth >= self.max_depth or r.random() < 0.3:
            return self.leaf(w, signed)
        a = self.expr(w, signed, depth + 1)
        b = self.expr(w, signed, depth + 1)
        op = r.choice(["+", "-", "*", "&", "|", "^", "<<", ">>", "/", "%", "cmp", "sel", "cast",
                       "neg", "not", "min", "max", "rot"])
        if op in "+-*":
            return f"(({t})({uc}{a} {op} {uc}{b}))"
        if op in "&|^":
            return f"(({t})({a} {op} {b}))"
        if op in ("<<", ">>"):
            sh = f"((({u}){b}) & {w - 1}U)"
            if op == "<<":
                return f"(({t})({uc}{a} << {sh}))"
            return f"(({t})({a} >> {sh}))"  # arithmetic shift of a signed value is implementation-defined (clang: arithmetic)
        if op in ("/", "%"):
            if signed:
                mn = f"(({t})(({u})1 << {w - 1}))"
                return f"(({b}) == 0 || (({a}) == {mn} && ({b}) == -1) ? ({t})({a}) : ({t})(({a}) {op} ({b})))"
            return f"(({b}) == 0 ? ({t})({a}) : ({t})(({a}) {op} ({b})))"
        if op == "cmp":
            c = r.choice(["<", "<=", ">", ">=", "==", "!="])
            return f"(({t})({a} {c} {b}))"
        if op == "sel":
            c = self.cond(depth + 1)
            return f"({c} ? {a} : {b})"
        if op == "cast":
            ow, osg = r.choice([(x[1], x[2]) for x in TYPES])
            inner = self.expr(ow, osg, depth + 1)
            return f"(({t}){inner})"
        if op == "neg":
            return f"(({t})(-{uc}{a}))"
        if op == "not":
            return f"(({t})(~{a}))"
        if op in ("min", "max"):
            c = "<" if op == "min" else ">"
            return f"(({a}) {c} ({b}) ? ({a}) : ({b}))"
        if op == "rot":
            k = r.randrange(1, w)
            return f"(({t})(({uc}{a} << {k}) | ({uc}{a} >> {w - k})))"
        raise AssertionError(op)

    def cond(self, depth=0):
        w, s = self.r.choice([(x[1], x[2]) for x in TYPES])
        c = self.r.choice(["<", "<=", ">", ">=", "==", "!="])
        return f"({self.expr(w, s, depth + 1)} {c} {self.expr(w, s, depth + 1)})"

    def stmts(self, n, indent, depth):
        out = []
        for _ in range(n):
            k = self.r.random()
            pad = "  " * indent
            if k < 0.15 and depth < 2:
                out.append(f"{pad}if {self.cond()} {{")
                out += self.stmts(self.r.randint(1, 3), indent + 1, depth + 1)
                out.append(f"{pad}}} else {{")
                out += self.stmts(self.r.randint(1, 3), indent + 1, depth + 1)
                out.append(f"{pad}}}")
            elif k < 0.22 and depth < 1:
                i = f"i{indent}"
                out.append(f"{pad}for (int {i} = 0; {i} < {self.r.randint(1, 4)}; {i}++) {{")
                out += self.stmts(self.r.randint(1, 3), indent + 1, depth + 1)
                out.append(f"{pad}}}")
            else:
                name, ctype, w, s = self.var()
                out.append(f"{pad}{name} = {self.expr(w, s)};")
        return out

    def generate(self) -> str:
        lines = []
        off = 0
        for i in range(self.n_vars):
            ctype, w, s = self.r.choice(TYPES)
            name = f"v{i}"
            nb = w // 8
            if off + nb <= N_IN:
                lines.append(f"  {ctype} {name}; __builtin_memcpy(&{name}, __in + {off}, {nb});")
                off += nb
            else:
                lines.append(f"  {ctype} {name} = {self.const(w, s)};")
            self.vars.append((name, ctype, w, s))
        body = self.stmts(self.n_stmts, 1, 0)
        outs = [f"  __out[{i}] = (uint64_t)({v[0]});" for i, v in enumerate(self.vars)]
        return (PRELUDE + f"uint8_t __in[{N_IN}];\nuint64_t __out[{self.n_vars}];\n\n"
                "void __test(void) {\n" + "\n".join(lines + body + outs) + "\n}\n")


CSMITH_DIR = Path(__file__).resolve().parent.parent / "tools" / "csmith" / "install"
# Small, scalar-only programs: no pointers/arrays/structs/unions (so every global is a scalar we can
# seed from __in and observe in __out), no volatiles/checksum/printf (no libc in the body), few
# functions and shallow blocks so KLEE and angr can enumerate paths within the budget.
CSMITH_OPTS = [
    "--no-pointers", "--no-arrays", "--no-structs", "--no-unions", "--no-volatiles", "--no-volatile-pointers",
    "--no-packed-struct", "--no-bitfields", "--no-checksum", "--no-argc", "--no-jumps", "--no-builtins",
    "--no-consts", "--no-const-pointers", "--no-float", "--no-inline-function", "--concise",
    "--max-funcs", "2", "--max-block-depth", "2", "--max-block-size", "3", "--max-expr-complexity", "4",
]
CSMITH_K = 4        # globals seeded from __in
CSMITH_MAX_OUT = 16
_GLOBAL_RE = re.compile(r"^static (u?int(?:8|16|32|64)_t) (g_\d+) = (.*);$", re.M)
_SAFE_RE = re.compile(r"STATIC (\w+)\nFUNC_NAME\((\w+)\)(.*?\n}\n)", re.S)


def _safe_math_defs():
    """name -> self-contained C definition of each Csmith safe-math wrapper (as `static` functions)."""
    txt = (CSMITH_DIR / "include" / "safe_math.h").read_text()
    return {m.group(2): f"static {m.group(1)}\nsafe_{m.group(2)}{m.group(3)}" for m in _SAFE_RE.finditer(txt)}


CSMITH_PRELUDE = """\
#include <stdint.h>
#include <limits.h>
#define UNDEFINED(__val) (__val)
#define LOG_INDEX
#define LOG_EXEC
"""


def _csmith_wrap(seed: int, cseed: int, opts, k, max_out):
    cmd = [str(CSMITH_DIR / "bin" / "csmith"), "--seed", str(cseed), *opts]
    src = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60).stdout
    main_at = src.index("\nint main ")
    body = src[:main_at]
    body = re.sub(r'^#include "csmith.h"\n', "", body, flags=re.M)
    body = re.sub(r"^volatile uint64_t csmith_sink_ = 0;\n", "", body, flags=re.M)
    body = re.sub(r"^static long __undefined;\n", "", body, flags=re.M)
    body = re.sub(r"^//.*\n", "", body, flags=re.M)
    globs = _GLOBAL_RE.findall(body)
    m = re.search(r"^static (\S+)\s+func_1\(void\);", body, re.M)
    ret_t = m.group(1)
    # __test goes after the prototypes and before the function definitions, so that seeded mutation
    # (which only mutates text after `void __test(void) {`) hits Csmith's code too.
    first_def = re.search(r"^static \S+\s+func_\d+\(.*\)\n\{", body, re.M).start()
    decls, defs = body[:first_def], body[first_def:]
    rng = random.Random(seed)
    lines = [f"  {name} = {init};" for _, name, init in globs]  # re-init: __test may run many times per process
    off = 0
    for ctype, name, _ in rng.sample(globs, min(k, len(globs))):
        nb = int(re.search(r"\d+", ctype).group()) // 8
        if off + nb > N_IN:
            continue
        lines.append(f"  __builtin_memcpy(&{name}, __in + {off}, {nb});")
        off += nb
    outs = [f"(uint64_t)func_1_ret"] + [f"(uint64_t){name}" for _, name, _ in globs]
    if len(outs) > max_out:
        outs = outs[:max_out - 1] + ["(" + " ^ ".join(outs[max_out - 1:]) + ")"]
    lines.append(f"  {ret_t} func_1_ret = func_1();")
    lines += [f"  __out[{i}] = {o};" for i, o in enumerate(outs)]
    used = set(re.findall(r"\bsafe_(\w+)\(", defs))
    safe = _safe_math_defs()
    missing = used - set(safe)
    if missing:
        raise ValueError(f"csmith seed {seed}: unknown safe-math wrappers {sorted(missing)}")
    prelude = CSMITH_PRELUDE + "\n".join(safe[n] for n in sorted(used))
    test = "void __test(void) {\n" + "\n".join(lines) + "\n}\n\n"
    src = (f"/* csmith --seed {cseed} {' '.join(opts)} */\n" + prelude
           + f"\nuint8_t __in[{N_IN}];\nuint64_t __out[{len(outs)}];\n\n" + decls.strip() + "\n\n"
           + test + defs.strip() + "\n")
    return src, len(outs)


def _csmith_ok(src: str, n_out: int, seed: int, n_inputs=32, timeout=5) -> bool:
    """Native smoke test: UBSan-clean and terminating on a few inputs. Csmith does not guarantee
    termination (e.g. `for (x = 0; x != -6; x = (uint8_t)(x - 1))`), and our symbolic globals can
    change the control flow Csmith reasoned about."""
    import tempfile
    from . import build
    rng = random.Random(seed ^ 0xC5)
    inputs = [bytes(N_IN), bytes([0xff] * N_IN)] + [bytes(rng.choice([0, 1, 0x7f, 0x80, 0xff, rng.getrandbits(8)])
                                                         for _ in range(N_IN)) for _ in range(n_inputs - 2)]
    with tempfile.TemporaryDirectory(prefix="csmith-chk-") as d:
        c = Path(d) / "prog.c"
        c.write_text(src)
        try:
            exe = build.native(c, Path(d) / "chk", N_IN, n_out, cc=build.CLANG, opt="-O0",
                               extra=("-fsanitize=undefined", "-fno-sanitize-recover=all"))
            outs = build.replay_many(exe, inputs, timeout=timeout)
        except (build.BuildError, subprocess.TimeoutExpired):
            return False
    return all(o is not None for o in outs)


def csmith_program(seed: int, opts=None, k=CSMITH_K, max_out=CSMITH_MAX_OUT, attempts=20, check=True):
    """Csmith program wrapped in the harness: K scalar globals overridden from __in, all scalar globals
    and func_1's return value written to __out. Returns (source, n_out).

    Deterministic in `seed`: Csmith seed `seed` is tried first; if the result fails the native smoke test,
    derived Csmith seeds are tried in a fixed order."""
    opts = CSMITH_OPTS if opts is None else opts
    for a in range(attempts):
        cseed = seed if a == 0 else random.Random(f"csmith-{seed}-{a}").getrandbits(31)
        src, n_out = _csmith_wrap(seed, cseed, opts, k, max_out)
        if not check or _csmith_ok(src, n_out, seed):
            return src, n_out
    raise RuntimeError(f"csmith: no terminating UB-free program for seed {seed} in {attempts} attempts")


def generate(gen: str, seed: int, **kw) -> Program:
    rng = random.Random(seed)
    if gen == "arith":
        g = ArithGen(rng, **kw)
        src = g.generate()
        return Program(src, N_IN, g.n_vars, gen, seed)
    if gen == "csmith":
        src, n_out = csmith_program(seed, **kw)
        return Program(src, N_IN, n_out, gen, seed)
    raise ValueError(f"unknown generator {gen}")


if __name__ == "__main__":
    import sys
    print(generate(sys.argv[2] if len(sys.argv) > 2 else "arith", int(sys.argv[1]) if len(sys.argv) > 1 else 0).source)
