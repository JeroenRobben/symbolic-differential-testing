# Lab notebook

## 2026-10-20 — setup

**Question.** Can we find compiler bugs by comparing source-level semantics (KLEE on clang -O0 IR) with
compiled-code semantics (angr on the clang-23 binary), path by path, with an SMT oracle?

**Prior work found** (see first conversation): Kapus & Cadar ASE'17 (differential testing *of* symbolic
executors across source/bitcode/binary); arm-tv / riscv-tv (Alive2-based IR→asm translation validation,
~46 LLVM backend bugs, per function, not per path); Alive2; Soliduzz (symbolic EMI for Solidity);
BinSym's remark that IR-level symbex cannot see compiler bugs. No paper found doing exactly this pairing.

**Toolchain.** No docker access (user not in docker group) → KLEE built from source (master 03d8b93)
against system LLVM 18 + Z3, with GCC and `-include cstdint` (clang-18 host fails against GCC 16 libstdc++).
Csmith built from source. angr 10.0.4 (claripy now in Rust: `angr.rustylib.claripy`; formulas exported
via `Solver.to_smt2()` and parsed with z3). Compiler under test: system clang 23.1.3.

**Design decisions.**
- Harness: `uint8_t __in[16]`, `uint64_t __out[M]`, `void __test(void)`. KLEE side binds outputs to a
  fresh symbolic array via `klee_assume(o[i] == __out[i])`, so each path's SMT2 = π ∧ o = f.
- Three detection channels per case/config: **symbolic** (oracle), **concrete** (one model per KLEE path
  replayed natively), **fuzz** (2000 random inputs natively). Symbolic-only detections measure what the
  approach adds.
- Recall benchmark: seeded single-site mutants compiled on the binary side only.
- Generator `arith`: UB-free by construction (arith in unsigned, narrow types widened to uint32 to avoid
  int promotion overflow, masked shifts, guarded division). Checked: 40 programs × 200 inputs UBSan-clean.

**Results so far.**
- Mutation sites inside division guards were equivalent mutants → excluded; recall denominator =
  mutants killed by any channel.
- `s000-seeded` (24 cases, O2, budget 30 s): recall_symbolic 8/9 = 0.89, 2 detections symbolic-only.
  FP rate 50 %, all `ref-engine`. Root cause: KLEE dumps still-running states at timeout as tests
  (`.early`), whose SMT2 has no output constraints → outputs unconstrained. Fixed by skipping `.early`.
- KLEE complete on only 15/24 cases within 30 s; ref path coverage by bin paths 0.38. → backlog.

**Next.** Verify the fix (s001-seeded), first real campaign c001.
