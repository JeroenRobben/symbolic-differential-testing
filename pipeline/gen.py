"""Test-program generators.

Every generated program exposes the same harness interface:
    uint8_t  __in[N_IN];    -- symbolic input bytes b0..b{N_IN-1}
    uint64_t __out[N_OUT];  -- observable outputs
    void     __test(void);  -- reads __in, writes __out
The programs must be free of undefined behaviour for every input.
"""
import random
from dataclasses import dataclass

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


def generate(gen: str, seed: int, **kw) -> Program:
    rng = random.Random(seed)
    if gen == "arith":
        g = ArithGen(rng, **kw)
        src = g.generate()
        return Program(src, N_IN, g.n_vars, gen, seed)
    raise ValueError(f"unknown generator {gen}")


if __name__ == "__main__":
    import sys
    print(generate("arith", int(sys.argv[1]) if len(sys.argv) > 1 else 0).source)
