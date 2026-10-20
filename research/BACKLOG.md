# Backlog (ranked; top = next)

1. ~~Verify the `.early` fix~~ done (E000, keep).
2. **First real campaign** `c001` on arith, seeds 0:200, O1/O2/O3/Os. Measure FP causes, coverage, throughput.
3. **KLEE path completion is the bottleneck** (15/24 complete at 30 s; seed 13: 0 paths). Also use early states: model of their π → native replay: KLEE times out on loop-heavy programs (only 15/24 complete).
   Investigate: per-case path counts; options — smaller loops in generator, KLEE `--search=bfs`,
   longer budget, or concolic seeding (run both engines along the same concrete seed paths).
4. **Oracle cost**: pairwise R_i × B_j is O(n·m) solver calls; 46 unknowns in s000. Ideas: prefilter pairs
   by evaluating both path conditions on a model of R_i; group bin paths; incremental solver.
5. **Ref-side coverage gap check**: when angr is complete, check whether a ref path region is not covered
   by any bin path (would indicate a miscompile that changes control flow into a crash/hang).
6. **Csmith generator**: Csmith programs with K scalar globals made symbolic; outputs = all scalar globals.
   Needs `--no-...` options to keep paths tractable.
7. **More configs**: `-march=x86-64-v3` (check angr AVX2 support), `-O2 -fno-...` variants, `-flto`.
8. **Generator variety**: add memory (local arrays with symbolic index, bounded), structs, bitfields,
   builtins (`__builtin_ctz`, popcount, bswap, overflow builtins), select/min/max idioms.
9. **Reduction**: install cvise (AUR or pip) and wire `reduce.py` for confirmed findings.
10. **Second engine pair** for cross-checks (SymCC/SymQEMU) — later.
11. **Real-code harnesses** once FP < 20 % on generated code.
